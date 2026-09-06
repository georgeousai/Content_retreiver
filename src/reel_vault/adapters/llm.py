"""The adapters that write text: tagging, query classification, collection
assignment, summarizing, ranking, compiling, and condensing a transcript.

All of them are one HTTP call to `/chat/completions` — the shape Groq,
OpenAI, DeepSeek, Qwen, Together, Moonshot, Mistral and Google's
compatibility endpoint all speak. Nothing here names a provider: which one
answers is a base URL, a key and a model name handed in at startup, so
moving off today's provider is an `.env` edit rather than a new adapter.

What is provider-specific, and stays here rather than leaking outward, is
that models return JSON wrapped in whatever they feel like — fences, a
preamble, a trailing apology. `_loads_json` absorbs that, because a reply
that fails to parse is never an error the user sees; it is silently the
wrong answer shape."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable

from openai import BadRequestError, OpenAI
from openai.types.chat import ChatCompletion

from reel_vault.config import ModelEndpoint
from reel_vault.models import (
    UNCATEGORIZED,
    CollectionAssignment,
    Comparison,
    NeighbourPlacement,
    QueryClassification,
    QueryKind,
    SummarySource,
)

logger = logging.getLogger(__name__)

# What a ranked answer says it ranked by when the model failed to say. Spelled
# out rather than left empty: the answer is shown to the user, and a blank
# would read as an unqualified verdict rather than a missing qualification.
UNSTATED_CRITERION = "no stated measure"

TAG_SYSTEM_PROMPT = (
    "You tag short social-media captions with topic keywords. Given a caption, "
    "reply with ONLY a JSON array of 1-5 short lowercase topic tags (single "
    "words or short phrases, no hashtags, no punctuation besides spaces/hyphens). "
    "Invent new tags freely; do not limit yourself to a fixed vocabulary. If the "
    "caption has no discernible topic, reply with an empty JSON array []."
)

INTENT_SYSTEM_PROMPT = """\
You classify a user's request against a personal saved-content vault of \
social-media posts. Reply with ONLY a JSON object: \
{"kind": "...", "author": "..." or null, "collection": "..." or null}

The vault files every post under exactly one COLLECTION, and you are given the \
collections that currently exist. If the request names one of them - "my Sales \
reels", "everything in Fitness", "what do my AI reels say" - copy that \
collection's name EXACTLY into `collection`, matching it even when the user's \
capitalisation differs. A topic merely mentioned ("reels about biceps") is NOT \
a collection unless it matches an existing one by name. Otherwise `collection` \
is null.

`kind` is exactly one of:
- "AUTHOR_FILTER" - the user wants everything from one specific creator, \
identified by handle or name (e.g. "show me @gymshark's reels", "what have I \
saved from Andrew Huberman"). Put the creator, without a leading @, in `author`.
- "LIST" - the user wants to browse/see the saved items matching a topic, as a \
list (e.g. "show me all my reels about AI", "what reels do I have on sourdough").
- "COMPARE_RANK" - the user wants the best, the top few, or a comparison \
between things their saved items describe (e.g. "what's the best bicep \
workout", "which of these meal preps is quickest", "rank the note-taking apps \
my reels mention").
- "EXTRACT_COMPILE" - the user wants a specific kind of THING pulled out of \
several saved items and gathered into one list (e.g. "give me all the \
interview questions from my AI reels", "every tool mentioned in my \
productivity reels", "compile the ingredients").
- "AGGREGATE" - the user wants content gathered and synthesized ACROSS several \
saved items into a written answer, without ranking it or listing one kind of \
thing out of it (e.g. "summarize what my finance reels say about index \
funds", "what do my reels say about morning routines").
- "SINGLE" - the user is looking for one specific saved item (e.g. "find that \
reel about transformer architecture").

The distinctions that matter:
- LIST hands back the saved items themselves. Everything below reads them and \
writes something new.
- COMPARE_RANK has to pick a winner; AGGREGATE does not. If the request \
contains "best", "top", "easiest", "most X", "better", or asks which one to \
choose, it is COMPARE_RANK.
- EXTRACT_COMPILE asks for instances of one kind of thing (questions, steps, \
tools, names, prices) merged into a list; AGGREGATE asks what the items say. \
"All the X from my Y reels" is EXTRACT_COMPILE, not AGGREGATE.

`author` is null unless kind is AUTHOR_FILTER. `collection` is independent of \
`kind`: "show me my Sales reels" is LIST with collection "Sales"; "summarize \
my Sales reels" is AGGREGATE with collection "Sales"; "the best of my Sales \
reels" is COMPARE_RANK with collection "Sales"."""

SUMMARY_SYSTEM_PROMPT = """\
You answer a user's question using ONLY what the user's saved reels provide. \
Each reel is labelled with the creator who posted it, and gives you up to \
three things: the caption they wrote, a transcript of what was said in the \
video, and a reading of what was shown on screen. Some reels have only a \
caption - those videos have not been read.

Write an answer, not an inventory. One line per reel saying what that reel is \
about is a table of contents, and the user is reading you precisely so they \
don't have to open the reels. Group the reels by what they actually say \
and let those shared points carry the structure. Where several creators make \
the same point, make it once and name them together.

Answer with the SUBSTANCE. If a reel lists four bicep hacks, name them; do \
not write "shares 4 bicep hacks".

Rules:
- Report only what the sources actually say. Never invent. The transcript and \
the on-screen reading are machine-made and imperfect: report what they say \
without correcting them into what you think was meant, and never guess at \
anything that happened between what they record.
- Do not credit a reel with answering the question just because it shares a \
topic word with it. A reel mentioning "habits" is not thereby advice on \
"growing a personal brand" - it has to actually say so. Example: asked "how \
do I grow my personal brand", a caption reading "comment HABITS for my list \
of habits" does NOT support writing "a list of habits that can help grow \
your personal brand" - nothing in that caption makes that claim. The correct \
answer there is that none of the sources give direct advice on the question \
asked.
- Open with one or two sentences answering the question directly, before any \
heading or bullet.
- Group by theme by default. Group by creator only when the user asked who \
said what.
- SKIP any reel that does not address the question. A reel that merely \
carries a relevant hashtag adds nothing - leave it out rather than padding \
the answer with it.
- Attribute inline as "(@handle)", and only where knowing the source matters.
- A reel whose only content is a bare title ("Five Year Journey") has not \
earned a line of its own. Fold it into a theme or leave it out.
- If none of the reels really answer the question, say so plainly. Where the \
reels that came closest have no transcript and no on-screen reading, say that \
their content is likely spoken in the video and has not been read yet.

Formatting - your reply is rendered in a chat app that supports NOTHING but \
these two markers:
- A section heading is a line starting with "## ". Use at most three, and only \
when the answer genuinely has sections; a short answer needs none.
- A bullet is a line starting with "- ".
Write everything else as plain sentences. Do NOT use tables, pipes, asterisks, \
underscores, backticks, or "#" for anything else - they reach the user \
literally."""


CONDENSE_SYSTEM_PROMPT = """\
You compress a machine-made reading of a short social-media video - either a \
transcript of what was said, or a description of what was on screen - down to \
what someone searching their saved videos would need.

Keep: every concrete claim, number, name, step, tool, price, and instruction. \
Keep the specifics, which are the only reason anyone will ever find this \
again.

Drop: greetings, sign-offs, "follow for more", "comment X below", repetition, \
filler, and stumbles. Drop anything that describes the video rather than \
saying what is in it.

Write plain sentences or short lines, no headings and no markup. Aim for a \
tenth of the length, less if the video was mostly filler.

Two rules that matter more than brevity:
- Add NOTHING. Every fact in your output must be in the input. Do not \
complete a half-finished thought, do not name the thing you think was being \
described, and do not resolve an ambiguity by picking the likelier reading. \
Example: given "so the first one is, you want to, yeah - just keep your \
elbows in", write "keep your elbows in" - NOT "the first tip is to keep your \
elbows tucked to isolate the bicep", which invents both a reason and a count \
the speaker never gave.
- If the input says nothing of substance - it is only a hook, a greeting, \
music, or an unintelligible fragment - reply with an empty string rather \
than manufacturing a summary of it. An empty reply throws the whole input \
away, so it is right only when there is genuinely nothing there to keep. \
Before emptying, check that you cannot name one concrete thing the input \
contains. If you can name one, condense it instead. Terse, list-like, \
instruction-shaped phrasing is what real instructions sound like, and is not \
a reason to empty anything."""

COMPARE_SYSTEM_PROMPT = """\
The user wants you to pick the best or the top few of something, out of what \
their saved videos say. Reply with ONLY a JSON object: \
{"criterion": "...", "answer": "..."}

`criterion` is the measure you ranked by, as a short phrase ("fewest \
ingredients", "most beginner-friendly", "strongest evidence given"). The \
request is usually ambiguous - "best" can mean most effective, quickest, \
cheapest, or easiest - so choose the reading the sources themselves best \
support, and name it. You are NOT asking the user a question; you are \
telling them which reading you used so they can re-ask if it was the wrong \
one.

`answer` is the ranked answer itself. Name the winner in the first sentence \
and say what makes it win under your criterion. Where a runner-up is close \
or wins under a different reading, say so briefly. Attribute inline as \
"(@handle)".

Rules:
- Rank only on what the sources actually say. If none of them supports a \
comparison on this question, say that plainly in `answer` instead of \
inventing a ranking, and put the criterion you looked for in `criterion`.
- Never credit a source with a claim it did not make, and never bridge a gap \
because two things are topically adjacent. A source about morning habits is \
not thereby advice on building a personal brand.
- A source that does not address the question is not a contender. Leave it \
out; do not rank it last to be thorough.
- Say what you cannot know. If ranking properly would need something none of \
the sources gives, name that gap in one clause rather than guessing past it.

Formatting inside `answer`: plain sentences, and lines starting with "- " for \
bullets. Nothing else - no tables, pipes, asterisks, underscores, backticks \
or "#". They reach the user literally."""

EXTRACT_SYSTEM_PROMPT = """\
The user wants a specific kind of thing pulled out of their saved videos and \
gathered into one list - the questions, the steps, the tools, the book \
titles, whatever they named. Reply with ONLY a JSON array of strings.

Each element is one item, written as the source gave it, trimmed to itself. \
Return the items and nothing else: no headings, no numbering, no "here are \
the items", no commentary elements.

Rules:
- Extract only items that are actually there. An empty array is the correct \
answer when the sources do not contain the thing asked for - much better than \
a plausible list nobody said.
- Merge duplicates. The same item phrased two ways across two videos is ONE \
element; keep the clearer wording.
- Do not complete a partial item, and do not generalise a specific one into \
the category you think it belongs to. Example: asked for interview questions, \
a source saying "they'll ask about a time you disagreed with your manager" \
yields "Tell me about a time you disagreed with your manager" - NOT "Conflict \
resolution questions", which is a topic, not a question anyone asked.
- Keep each item short enough to scan. If a source gives an item plus a long \
justification, keep the item.
- Preserve the order items appeared in where there is one (steps in a \
recipe); otherwise most-mentioned first."""


RERANK_SYSTEM_PROMPT = """\
The user asked a question about videos they saved. A rough search picked the \
numbered videos below as possibly relevant. It matches on subject matter and \
wording alone, so some of them are here only for sharing vocabulary with the \
question. Decide which ones actually answer it.

Reply with ONLY a JSON array of the numbers you keep, best answer first: \
[3, 1]. Reply [] if none of them answer the question.

KEEPING is the default. Drop a video only for one of two reasons: the \
question explicitly ruled it out, or it is about a plainly different subject. \
Anything else stays, including a video that only partly helps and a video too \
thin to tell much about. The two mistakes do not cost the same. A video kept \
loosely costs the user one glance and they can see for themselves. A video \
wrongly dropped is one they are never told they have, and they cannot ask for \
what they do not know was there. When you are unsure at all, keep it.

The one thing you must do that the search could not: read the part of the \
question saying what the user does NOT want. "X, not Y", "X rather than Y" \
and "actually X" mean a video that is Y is ruled out even though it sits \
squarely in the right subject -- and that is usually the single strongest \
reason to drop anything. The search shortlisted on wording, so it read \
"not Y" as more words about Y and ranked the excluded half first. This is the \
main reason you are being asked.

Judge on what a video contains: the caption its creator wrote, what was said \
in it, and what was shown on screen. A recipe is still a recipe when its \
caption is one word and the steps are only on screen.

A broad question wants breadth. Where the user asked about a subject rather \
than for one particular thing, everything on that subject stays, and it is \
not your job to pick the best of them.

Order what you keep best-answer-first.

Use only the numbers shown, each at most once. Never invent a number, and \
never reply with anything but the JSON array."""


COLLECTION_SYSTEM_PROMPT = (
    "You file a saved social-media post into a personal library. You are given "
    "the post's caption, the library's EXISTING collections (each with its "
    "existing sub-collections), and the posts already in the library whose "
    "captions most resemble this one, with where each of those was filed.\n\n"
    "Rules, in priority order:\n"
    f"1. First judge whether the caption itself carries enough real subject "
    f"matter to determine a topic. Generic hooks, reaction lines, dates, or "
    f"vague teasers (e.g. \"5 years ago this wasn't a thing\", \"wait for it\", "
    f"\"POV:\") carry NO topic on their own, even if the video behind them "
    f"might. If that is all you have, respond with "
    f'{{"collection": "{UNCATEGORIZED}", "subcollection": null}} — do NOT pick '
    f"an existing collection just because one happens to exist. Guessing a "
    f"specific-sounding topic from a caption that does not support it is "
    f"worse than admitting you don't know.\n"
    "2. Otherwise, STRONGLY prefer reusing an existing collection that "
    "actually matches the caption's real content. Only invent a new one if "
    "the caption clearly does not belong in any existing one.\n"
    "2b. Weigh the SIMILAR POSTS heavily: they show where this library "
    "actually puts posts like this one, which the collection names alone "
    "cannot tell you. A similar post marked [user-placed] was filed by the "
    "user personally and is stronger evidence than one this classifier "
    "placed unaided - where they disagree, follow the user. But similar "
    "WORDING is not the same as the same TOPIC: a neighbour is evidence to "
    "weigh, never an instruction to copy, and a caption that plainly "
    "belongs elsewhere goes elsewhere.\n"
    "2c. Do NOT let a sub-collection name pull a post onto the wrong "
    "collection. Matching a narrow name is not a reason to file a post on a "
    "shelf whose subject it does not share.\n"
    "3. Give it a sub-collection whenever the caption's content is specific "
    "enough to name one narrower than the collection itself (e.g. \"Bicep "
    "Workouts\" under \"Fitness\", \"Cold Outreach\" under \"Sales\") — do "
    "not leave it null purely because none exist yet for that collection; "
    "you invent the first one the same way you invented the collection. "
    "Reuse an existing sub-collection over inventing a near-duplicate. Use "
    "null only when the caption's topic really is no narrower than the "
    "collection as a whole.\n"
    "4. Collection names are short Title Case noun phrases (e.g. \"AI\", "
    "\"Fitness\", \"Personal Finance\").\n"
    "5. Never rename or re-word an existing collection: copy it exactly.\n\n"
    'Reply with ONLY a JSON object: {"collection": "...", "subcollection": '
    '"..." or null}'
)


def chat_client(endpoint: ModelEndpoint) -> OpenAI:
    """A client pointed at whichever provider is configured.

    The `openai` package is used as an HTTP client for a wire format, not as
    a commitment to OpenAI: `base_url` is what decides who answers, and every
    provider this app is likely to use serves that format.
    """
    return OpenAI(base_url=endpoint.base_url, api_key=endpoint.api_key)


class TruncatedResponse(RuntimeError):
    """The model ran out of output budget before saying anything.

    Its own type because the caller must not mistake it for an answer. A
    reasoning model spends completion tokens thinking before it writes, and
    when the thinking alone exhausts the budget the reply comes back with
    `finish_reason="length"` and an empty `content` — which is byte-for-byte
    what a model deliberately saying nothing looks like.

    Conflating those two cost this project days. `openai/gpt-oss-20b` emptied
    a 713-character recipe on 9 runs in 10, and the whole of it was read as a
    judgement the model was making about the recipe: prompts were rewritten,
    counter-examples added and removed, two providers compared. The response
    was truncated every time — 2046 reasoning tokens of a 2048-token budget,
    zero tokens left to answer with. See
    `.scratch/reel-vault-media-pipeline/STATUS.md`.
    """


def content_of(
    response: ChatCompletion,
    *,
    model: str,
    context: str,
    empty_reply_is_meaningful: bool = False,
) -> str:
    """The text of a reply, with one cut off before it started told apart
    from one that is deliberately empty.

    Module-level, and not a method on `_ChatAdapter`, because not every call
    this app makes fits that class: the vision adapter sends image parts and
    no system prompt, so it cannot share `_complete` -- and being outside
    `_complete` is precisely how it went a full audit without this check,
    reintroducing the bug that audit was for. Anything that reads a
    `/chat/completions` reply reads it through here.

    `empty_reply_is_meaningful` decides which of the two a caller can afford
    to confuse. Callers that parse what comes back -- a tag list, a JSON
    classification -- already degrade sensibly from an unparseable reply, so
    they take a warning in the log. Callers for which "nothing" is itself an
    answer cannot tell the two apart on their own, and ask to be told.
    """
    choice = response.choices[0]
    content = choice.message.content or ""
    if not content.strip() and choice.finish_reason == "length":
        message = (
            f"{model} used its whole output budget without answering ({context})"
        )
        if empty_reply_is_meaningful:
            raise TruncatedResponse(message)
        logger.warning("%s; treating it as no answer", message)
    return content


def _is_about_reasoning_effort(error: BadRequestError) -> bool:
    """Whether a 400 is the provider objecting to `reasoning_effort` itself.

    Checked rather than assumed, because a bad request has many other causes
    — a context length exceeded, a content filter, a model name that does not
    exist — and retrying those without the parameter would spend a second
    call to fail the same way, while logging something untrue about why.
    """
    return "reasoning_effort" in str(error)


class _ChatAdapter:
    """Shared request boilerplate for the chat-completion adapters below."""

    def __init__(self, *, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model
        # Discovered on first use rather than configured: whether a provider
        # accepts `reasoning_effort` is a fact about the endpoint, and asking
        # the operator to know it would be one more setting to get wrong.
        self._reasoning_effort_unsupported = False

    def _complete(
        self,
        *,
        system_prompt: str,
        user_content: str,
        temperature: float,
        reasoning_effort: str | None = None,
        empty_reply_is_meaningful: bool = False,
    ) -> str:
        """One chat call, its reply read through `content_of`.

        `empty_reply_is_meaningful` is passed straight down; see `content_of`
        for what it decides. Most adapters here parse what comes back — a tag
        list, a JSON classification — and already degrade sensibly from an
        unparseable reply: no tags, `SINGLE`, `Uncategorized`. The condenser
        is the exception, and the reason the distinction exists at all.

        `reasoning_effort` is passed only when a caller asks for it. A
        provider that rejects the parameter has the call remade without it,
        once — the answer is remembered on the instance, so this costs one
        wasted request per process rather than one per call.
        """
        extra = (
            {"reasoning_effort": reasoning_effort}
            if reasoning_effort and not self._reasoning_effort_unsupported
            else {}
        )
        try:
            response = self._request(system_prompt, user_content, temperature, extra)
        except BadRequestError as exc:
            if not extra or not _is_about_reasoning_effort(exc):
                raise
            logger.info(
                "%s does not accept reasoning_effort; dropping it for the "
                "rest of this run",
                self._model,
            )
            self._reasoning_effort_unsupported = True
            response = self._request(system_prompt, user_content, temperature, {})

        return content_of(
            response,
            model=self._model,
            context=f"{len(user_content)} chars in",
            empty_reply_is_meaningful=empty_reply_is_meaningful,
        )

    def _request(
        self, system_prompt: str, user_content: str, temperature: float, extra: dict
    ) -> ChatCompletion:
        return self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            **extra,
        )


class ChatTagger(_ChatAdapter):
    def tag(self, caption: str) -> list[str]:
        content = self._complete(
            system_prompt=TAG_SYSTEM_PROMPT, user_content=caption, temperature=0.2
        )
        return _parse_tag_list(content or "[]")


class ChatQueryIntent(_ChatAdapter):
    def classify(self, query: str, collections: list[str]) -> QueryClassification:
        existing = ", ".join(sorted(collections)) if collections else "(none yet)"
        content = self._complete(
            system_prompt=INTENT_SYSTEM_PROMPT,
            user_content=f"Existing collections: {existing}\n\nRequest:\n{query}",
            temperature=0.0,
        )
        return _parse_classification(content, collections)


class ChatCollectionAssigner(_ChatAdapter):
    def assign(
        self,
        caption: str,
        known: dict[str, list[str]],
        neighbours: list[NeighbourPlacement],
    ) -> CollectionAssignment:
        known_block = (
            json.dumps(known, indent=2) if known else "(none yet — this is the first post)"
        )
        content = self._complete(
            system_prompt=COLLECTION_SYSTEM_PROMPT,
            user_content=(
                f"Existing collections:\n{known_block}\n\n"
                f"Similar posts already in the library:\n"
                f"{_format_neighbours(neighbours)}\n\n"
                f"Caption:\n{caption}"
            ),
            temperature=0.0,
        )
        return _parse_assignment(content, known)


class ChatSummarizer(_ChatAdapter):
    def summarize(self, query: str, sources: list[SummarySource]) -> str:
        return self._complete(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            user_content=_question_with_sources(query, sources),
            temperature=0.3,
        )


class ChatComparer(_ChatAdapter):
    def compare(self, query: str, sources: list[SummarySource]) -> Comparison:
        content = self._complete(
            system_prompt=COMPARE_SYSTEM_PROMPT,
            user_content=_question_with_sources(query, sources),
            # Ranking is a judgement that should not change between two
            # identical askings of the same question.
            temperature=0.0,
        )
        return _parse_comparison(content)


class ChatItemExtractor(_ChatAdapter):
    def extract_items(self, query: str, sources: list[SummarySource]) -> list[str]:
        content = self._complete(
            system_prompt=EXTRACT_SYSTEM_PROMPT,
            user_content=_question_with_sources(query, sources),
            temperature=0.0,
            # Measured truncating on real vault content, and silently: at 9
            # reels of media-rich text it spent all 2046 available reasoning
            # tokens and returned nothing, `_parse_items` turned that into
            # `[]`, and the user got an empty compilation that looked like an
            # answer. Asked for shallow reasoning on the same input it uses
            # 737 and returns 14 items.
            #
            # Only this adapter, and not the comparer or summarizer beside
            # it, because only this one was measured to need it: on the same
            # 9 reels the comparer used 665 reasoning tokens and the
            # summarizer 916. Enumerating *every* item across many sources is
            # combinatorially harder than picking a winner out of them, so
            # the task shape rather than the input size is what runs the
            # budget out.
            #
            # "low" rather than "medium" is untested: the daily token cap ran
            # out before that comparison could be made. Low is known to fix
            # the truncation, and a degraded-but-complete list beats an empty
            # one presented as an answer, so it ships as the safe end of the
            # range. Whether medium clears the budget too, and reads the
            # sources any better for it, is an open question.
            reasoning_effort="low",
        )
        return _parse_items(content)


class ChatReranker(_ChatAdapter):
    def rerank(self, query: str, sources: list[SummarySource]) -> list[int]:
        content = self._complete(
            system_prompt=RERANK_SYSTEM_PROMPT,
            user_content=_question_with_numbered_sources(query, sources),
            # Which saved videos answer a question is not a matter of taste,
            # and the same question asked twice returning different reels is
            # the kind of thing that costs a user their trust in the answer.
            temperature=0.0,
            # Deliberately NOT `reasoning_effort="low"`, unlike the extractor
            # and condenser above, and measured rather than assumed. On
            # "Which of my Strength Training reels is about actual training
            # technique, not just motivation?" against the live shelf,
            # 2026-09-06, three runs each:
            #
            #   low       60-78 reasoning tokens    1/3 correct, 2/3 "[]"
            #   medium    528-1081                  2/3 correct, 1/3 one extra
            #   default   557-586                   3/3 correct
            #
            # Reading several videos and judging each against a question that
            # excludes half its own subject is not the mechanical work
            # condensing is. Starved of budget the model does not answer
            # worse, it answers "none of them" -- which is the one reply that
            # empties a shelf holding the answer, and which nothing
            # downstream can tell from a considered rejection. There is no
            # truncation risk to trade against: every run finished on `stop`
            # well inside the budget that broke the extractor at 2046.
        )
        return _parse_kept_indices(content, len(sources))


class ChatContentCondenser(_ChatAdapter):
    def condense(self, text: str) -> str:
        return self._complete(
            system_prompt=CONDENSE_SYSTEM_PROMPT,
            user_content=text,
            # Compressing text that is already known to be worth compressing
            # is mechanical, and on a reasoning model the deliberation is
            # what breaks it: left to think as long as it likes,
            # `gpt-oss-20b` spent 2046 tokens of a 2048-token budget
            # reasoning about a recipe and had none left to answer with,
            # which is the whole of the "condenser empties real content" bug.
            # Asked for shallow reasoning it answers the same question in 101
            # tokens, and 240 completion tokens against the 3135 the same
            # call takes when simply given a bigger budget - a thirteenth of
            # the cost, on a call made twice per reel against a free tier.
            reasoning_effort="low",
            # The one adapter that cannot read an empty reply as an answer:
            # returning nothing is how it reports a transcript with nothing
            # in it, so a truncated reply and a considered one are the same
            # bytes. Being told is the whole fix for the bug above.
            empty_reply_is_meaningful=True,
            # Nothing here is a judgement call: the job is to drop filler and
            # keep specifics, and variation between runs is only a chance to
            # drop a different fact.
            temperature=0.0,
        ).strip()


def _format_neighbours(neighbours: list[NeighbourPlacement]) -> str:
    """The similar posts, each with where it was filed and by whom.

    A placement the user made is labelled as such: the model is told to
    prefer it over one the classifier made unaided, so that a mistake this
    classifier already made cannot quietly become the precedent for the next
    reel that resembles it.
    """
    if not neighbours:
        return "(none yet — this is the first post)"
    lines = []
    for neighbour in neighbours:
        where = neighbour.collection
        if neighbour.subcollection:
            where = f"{where} > {neighbour.subcollection}"
        who = " [user-placed]" if neighbour.user_placed else ""
        lines.append(
            f'- filed under {where}{who} (similarity {neighbour.similarity:.2f}): '
            f'"{neighbour.caption[:160]}"'
        )
    return "\n".join(lines)


def _question_with_sources(query: str, sources: list[SummarySource]) -> str:
    """The one user message all three answer-writers share. They differ in
    what they are told to do with the sources, never in how the sources are
    presented — one shape means a prompt fix for one of them is a prompt fix
    for all three."""
    block = "\n\n".join(_format_source(source) for source in sources)
    return f"Question: {query}\n\nSaved videos:\n{block}"


def _question_with_numbered_sources(query: str, sources: list[SummarySource]) -> str:
    """The same block the answer-writers get, with each reel numbered from 1.

    Numbered because the reranker answers *about* these reels rather than
    from them, and needs a way to name one. One-based because the reply is
    written by a model reading a list, and a list a person would read starts
    at one; the caller subtracts.
    """
    block = "\n\n".join(
        _format_source(source, bullet=f"{index}.")
        for index, source in enumerate(sources, start=1)
    )
    return f"Question: {query}\n\nSaved videos:\n{block}"


def _format_source(source: SummarySource, bullet: str = "-") -> str:
    """One reel as the answer-writers see it: who made it, what they wrote,
    and — where the video has been read — what was said and shown in it.

    The three are labelled separately rather than run together. A creator's
    own caption and a machine's reading of their video are different kinds of
    evidence, and a transcript in particular is an imperfect hearing: leaving
    the model unable to tell them apart would let a transcription error be
    reported as something the creator wrote down. An unknown creator is said
    to be unknown rather than left blank, which the model could otherwise
    read as the previous source's author.
    """
    if source.author_handle and source.author_name:
        who = f"{source.author_name} (@{source.author_handle})"
    else:
        who = source.author_handle or source.author_name or "unknown creator"

    lines = [f"{bullet} [by {who}] caption: {source.caption}"]
    if source.transcript:
        lines.append(f"  spoken in the video: {source.transcript}")
    if source.frame_text:
        lines.append(f"  shown on screen: {source.frame_text}")
    return "\n".join(lines)


def _loads_json(content: str) -> object | None:
    """Parse a model's JSON reply, tolerating the ```json fences and stray
    preamble chat models wrap answers in. Returns None if nothing parses.

    Being strict here is expensive: an unparsed reply is not an error the
    user ever sees, it is silently the wrong answer shape."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)```", content, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    # Fall back to the outermost object/array anywhere in the reply.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = content.find(opener), content.rfind(closer)
        if start != -1 and end > start:
            candidates.append(content[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _parse_classification(
    content: str, collections: list[str] | None = None
) -> QueryClassification:
    """Parse the classifier's JSON. Anything unparseable falls back to SINGLE —
    the narrowest, cheapest answer shape, and the one the vault has always
    defaulted to."""
    parsed = _loads_json(content)
    if parsed is None:
        logger.warning("Query classifier returned non-JSON content: %r", content)
        return QueryClassification(kind=QueryKind.SINGLE)

    if not isinstance(parsed, dict):
        return QueryClassification(kind=QueryKind.SINGLE)

    raw_kind = str(parsed.get("kind") or "").strip().upper()
    try:
        kind = QueryKind[raw_kind]
    except KeyError:
        logger.warning("Query classifier returned unknown kind: %r", raw_kind)
        return QueryClassification(kind=QueryKind.SINGLE)

    raw_author = parsed.get("author")
    author = str(raw_author).strip().lstrip("@") or None if raw_author else None
    if kind is not QueryKind.AUTHOR_FILTER:
        author = None
    elif author is None:
        # An author filter with nobody to filter on is not actionable; the
        # semantic path at least stands a chance of matching the handle text.
        logger.warning("Author-filter classification carried no author: %r", content)
        return QueryClassification(kind=QueryKind.LIST)

    raw_collection = parsed.get("collection")
    collection = str(raw_collection).strip() if raw_collection else None
    if collection:
        # Only a collection the vault actually holds can be filtered on; a
        # near-miss name is snapped back onto the real one, and anything
        # invented is dropped so retrieval falls back to semantic search.
        collection = _match_collection(collection, collections or [])

    return QueryClassification(kind=kind, author=author, collection=collection)


def _match_collection(name: str, collections: list[str]) -> str | None:
    for candidate in collections:
        if candidate.casefold() == name.casefold():
            return candidate
    logger.info("Classifier named an unknown collection: %r", name)
    return None


def _parse_assignment(content: str, known: dict[str, list[str]]) -> CollectionAssignment:
    """Parse the model's JSON, then snap near-miss names back onto existing
    collections so casing/whitespace drift can't fork a duplicate collection."""
    parsed = _loads_json(content)
    if parsed is None:
        logger.warning("Collection assigner returned non-JSON content: %r", content)
        return CollectionAssignment(collection=UNCATEGORIZED)

    if not isinstance(parsed, dict):
        return CollectionAssignment(collection=UNCATEGORIZED)

    collection = str(parsed.get("collection") or "").strip() or UNCATEGORIZED
    raw_sub = parsed.get("subcollection")
    subcollection = str(raw_sub).strip() if raw_sub else None

    collection = _canonicalize(collection, known.keys())
    if subcollection:
        subcollection = _canonicalize(subcollection, known.get(collection, []))
    return CollectionAssignment(collection=collection, subcollection=subcollection)


def _canonicalize(name: str, existing: Iterable[str]) -> str:
    """Return the existing spelling of `name` if one matches case-insensitively."""
    for candidate in existing:
        if candidate.casefold() == name.casefold():
            return candidate
    return name


def _parse_comparison(content: str) -> Comparison:
    """Parse the comparer's JSON.

    An unparseable reply still has to name a criterion: `CompareAnswer`
    promises the user that the measure used was stated, and a silently blank
    one would turn a parse failure into an answer that looks unqualified.
    """
    parsed = _loads_json(content)
    if not isinstance(parsed, dict):
        logger.warning("Comparer returned non-JSON content: %r", content)
        return Comparison(text=content.strip(), criterion=UNSTATED_CRITERION)

    text = str(parsed.get("answer") or "").strip()
    criterion = str(parsed.get("criterion") or "").strip() or UNSTATED_CRITERION
    if not text:
        logger.warning("Comparer returned no answer: %r", content)
        return Comparison(text=content.strip(), criterion=criterion)
    return Comparison(text=text, criterion=criterion)


def _parse_items(content: str) -> list[str]:
    """Parse the extractor's JSON array, dropping duplicates it left in.

    Merging duplicates is the model's job and it is told so, but a compiled
    list is precisely where a repeat is most visible, so the same guarantee
    is enforced here rather than trusted.
    """
    parsed = _loads_json(content)
    if not isinstance(parsed, list):
        logger.warning("Item extractor returned non-JSON content: %r", content)
        return []

    seen: dict[str, str] = {}
    for item in parsed:
        text = str(item).strip()
        if text:
            seen.setdefault(text.casefold(), text)
    return list(seen.values())


def _parse_kept_indices(content: str, count: int) -> list[int]:
    """Parse the reranker's array of one-based numbers into indices.

    Two failures have to stay distinguishable here, because they mean
    opposite things. A reply of `[]` is the model saying none of the
    shortlisted reels answer the question, which is exactly what this call
    exists to be able to hear. A reply that does not parse, or that names
    nothing real, is the model failing to answer at all — and reading that as
    "none of them" would turn every bad reply into a confident "nothing
    matched" for a user whose vault does hold the answer. So an unusable
    reply keeps every candidate, in the order similarity already put them,
    which is what the vault did before there was a reranker.

    Out-of-range and repeated numbers are dropped rather than trusted: they
    are the two ways a list of numbers goes wrong, and either would otherwise
    reach the user as a duplicated or a wrong reel.
    """
    parsed = _loads_json(content)
    if not isinstance(parsed, list):
        logger.warning("Reranker returned non-JSON content: %r", content)
        return list(range(count))

    kept: dict[int, None] = {}
    for value in parsed:
        try:
            index = int(value) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < count:
            kept.setdefault(index, None)

    if parsed and not kept:
        # It answered with something, and none of it named a reel on offer.
        logger.warning(
            "Reranker named none of the %d reels it was given: %r", count, content
        )
        return list(range(count))
    return list(kept)


def _parse_tag_list(content: str) -> list[str]:
    parsed = _loads_json(content)
    if parsed is None:
        logger.warning("Tagger returned non-JSON content: %r", content)
        return []

    if not isinstance(parsed, list):
        return []
    return [str(tag).strip().lower() for tag in parsed if str(tag).strip()]
