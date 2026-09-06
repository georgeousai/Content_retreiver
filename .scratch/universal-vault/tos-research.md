# ToS / Developer Terms research — download-and-transcribe risk (Instagram, TikTok, YouTube)

Researched 2026-08-29, for the "Reel Vault" / "Universal Vault" product: a
commercial, multi-tenant SaaS where paying users share links to Instagram
Reels, TikTok videos, and YouTube Shorts (content they do not own), and the
product programmatically downloads the video, transcribes the audio, and
sells search/summarization features built on that transcript to many end
users. The question is commercial/redistribution risk under each platform's
own current terms — not personal fair use.

**Sourcing method note:** Every quote below is attributed to an exact
official URL (help.instagram.com, developers.facebook.com,
facebook.com/legal, tiktok.com/legal, developers.tiktok.com,
youtube.com, developers.google.com). Direct `WebFetch` of
`help.instagram.com` returned only an empty JS shell (client-rendered SPA —
the tool could not execute the page's JavaScript), and the entire
`tiktok.com` / `developers.tiktok.com` domain was unreachable from this
environment (`ECONNREFUSED` at the network level, on every path tried,
including a bare connectivity test — this looks like a network-level block
of the TikTok domain in this sandbox, not a page-specific issue). For those
two cases only, the quotes below were retrieved via web search snippets that
quote the live official page verbatim (Google's indexer renders/reads the
actual page and the search tool surfaced the quoted substring) — the URL
cited is still the platform's own primary document, and the exact quoted
string is what search indexing captured from that live page, not a
paraphrase from a secondary blog. Where a secondary source (blog, SociaVault,
Phyllo, etc.) appeared only as a *summary* rather than a verbatim quote of a
primary page, it was not used as evidence for any claim below — only used to
locate the correct primary URL to then quote from directly (Instagram/Meta
pages, and all YouTube pages, were fetched directly and quoted from the live
primary document).

---

## 1. Instagram / Meta

### 1a. Automated access / scraping / downloading by third parties without the official API

**Explicitly prohibited.** Instagram's Terms of Use (help.instagram.com,
under "IV. Additional Rights We Retain" / account-access section) states:

> "You can't attempt to create accounts or access or collect information in
> unauthorised ways. This includes creating accounts or accessing or
> collecting information in an automated way without our express permission,
> regardless of whether such automated access or collection is undertaken
> while logged in to an Instagram account."
— https://www.facebook.com/help/instagram/581066165581870?locale=en_US (mirrors help.instagram.com/581066165581870)

The same page also prohibits commercializing anything obtained this way:

> "You can't sell, licence or purchase any account or data obtained from us
> or our Service, regardless of whether such data was obtained while logged
> in."
— same URL as above

Instagram/Meta's dedicated **Automated Data Collection Terms** (a separate,
linked document that the main Terms of Use incorporates by reference) is
even more explicit and is the controlling document for anything automated:

> "You will not engage in Automated Data Collection without first obtaining
> Meta's express written permission."
— https://www.facebook.com/legal/automated_data_collection_terms (Section 2, "Effective October 7, 2024")

It defines the covered conduct broadly (not just headless-browser scraping):

> "Collection of data from Meta Company Products via automated or
> programmatic tools capable of navigating or indexing the surface-layer of
> the World Wide Web"
— same URL, Section 8 (definitions)

Even where permission *is* granted, use is narrowly restricted to search-engine
indexing and link-preview purposes, and downstream commercial use is barred:

> Data "shall only be Used for the purpose of (i) providing results for your
> Search Engine, or (ii) displaying previews of Meta URLs"
> "Transferring, selling, licensing or sublicensing Collected Data...to any
> third party" is prohibited, including "commercial search services"
— same URL, Section 4

**Conclusion for 1a:** downloading Reels video by any means other than the
official, permissioned Graph API is explicitly prohibited, both under the
general Terms of Use and under the more specific Automated Data Collection
Terms, and would not fit even if permission were somehow granted (the
permitted-purposes list — search indexing, link previews — has no
transcription/summarization category).

### 1b. Does a compliant official API path exist for this use case?

**No compliant path exists for the described use case.** Instagram's
official API is the Instagram Platform API (Meta Graph API for Instagram),
governed by the **Meta Platform Terms**
(https://developers.facebook.com/terms/). Its own documentation states the
access model directly:

> "Note that a permission only allows access to data created by the app user
> who granted the permission." … "There are a few endpoints that allow apps
> to access data not created by the app user, but the accessible data is
> limited and public" (limited to hashtag-search discovery, not per-Reel
> download).
— https://developers.facebook.com/docs/instagram-platform/overview

In practice this means: the API can only read/manage content belonging to
the **Instagram Business/Creator account that has authorized the app** — it
has no endpoint that lets a third-party app fetch the video file (or audio
track) of an arbitrary other user's Reel just because a Reel Vault end user
pasted that Reel's public URL. Reel Vault's core use case (any user shares
*any* public creator's Reel URL, the product fetches that video) has no
supported endpoint at all — this is a capability gap, not merely a stricter
license term.

Even where the Graph API *is* usable (a business's own content), the Meta
Platform Terms impose real constraints on a commercial, multi-tenant product:

> Prohibited: "Processing Platform Data for purposes other than the
> applicable permitted purposes set forth in Meta's Developer Docs."
— https://developers.facebook.com/terms/, Section 3.a.viii

> "Selling, licensing, or purchasing Platform Data" — prohibited.
— same URL, Section 3.a.iv

> "You may only share Platform Data in compliance with these Terms...only in
> the following circumstances" (legal requirement, Service Providers under
> contract, express user consent, or specific third parties bound
> contractually not to violate the Terms).
— same URL, Section 3.c

> "Delete all Platform Data as soon as reasonably possible" when "retaining
> the Platform Data is no longer necessary for a legitimate business
> purpose."
— same URL, Section 3.d.i.2

**AMBIGUOUS — needs legal review:** whether AI-generated transcripts/summaries
derived from Platform Data would themselves count as "Platform Data" subject
to the deletion/no-resale/no-third-party-sharing rules above, or whether a
sufficiently transformed derivative escapes that classification, is not
addressed anywhere in the text and would need a lawyer's reading (and likely
a direct question to Meta's developer support/legal team) rather than a
plain-text answer.

### 1c. Explicit clauses on caching/long-term storage or redistributing derived data

Covered above (1b): Meta Platform Terms require deletion of Platform Data
once no longer needed for a "legitimate business purpose" (Section 3.d.i.2),
and restrict both selling Platform Data (3.a.iv) and sharing it with third
parties outside narrow carve-outs (3.c). No provision anywhere in the
fetched Meta or Instagram documents affirmatively addresses AI-generated
summaries or transcripts as a distinct category — silent on that specific
point, which is the ambiguity flagged in 1b.

### 1d. Documented enforcement patterns

> "We may take enforcement action at any time, including while we
> investigate your App(s), with or without notice to you... suspending or
> permanently removing your App(s) and account, removing your access and
> your App's access to Platform" … and may "suspend or end your App's access
> to any Platform APIs, permissions, or features" within 28 days of non-use.
— https://developers.facebook.com/terms/, Section 7.e (Suspension and Termination)

> Meta "may take enforcement action... including... revoking your permission
> to engage in Automated Data Collection"
— https://www.facebook.com/legal/automated_data_collection_terms, Section 5

Instagram's user-facing Terms of Use also reserve a broad, low-notice
termination right:

> "We can refuse to provide or stop providing all or part of the Service to
> you (including terminating or disabling your access to the Meta Products
> and Meta Company Products) immediately to protect our community or
> services, or if you create risk or legal exposure for us."
— https://www.facebook.com/help/instagram/581066165581870?locale=en_US, Section 6

---

## 2. TikTok

### 2a. Automated access / scraping / downloading by third parties without the official API

**Explicitly prohibited**, in both the general (user-facing) Terms of
Service and the Developer Terms of Service:

> "You may not use any robot, spider, crawler, scraper, or other automated
> means or interface not provided by us to access the Services or extract
> data without our prior written permission."
— https://www.tiktok.com/legal/page/row/terms-of-service/en (row = rest-of-world)

> "scrape, crawl, export or otherwise extract any data or content in any
> form, for any purpose, from the Platform using any automated system or
> software, including automated 'bots', except as approved in writing by
> TikTok"
— https://www.tiktok.com/legal/page/us/terms-of-service/en

> Content may not be "downloaded, copied, reproduced, distributed,
> transmitted, broadcast, displayed, sold, licensed or otherwise exploited
> for any purpose whatsoever without [TikTok's/rights holders'] prior
> written consent" — and use "for any purpose not expressly permitted by
> these Terms is strictly prohibited."
— https://www.tiktok.com/legal/page/row/terms-of-service/en

The Developer Terms separately confirm this applies to developer-side
automation too (a scraper built as part of a "developer" integration is not
exempted just because it's calling itself a developer tool):

> Developers may not use "any robot, spider, site search or retrieval
> application, or other device to collect information about users of the
> TikTok Developer Services for any unauthorized purposes."
— https://www.tiktok.com/legal/page/global/tik-tok-developer-terms-of-service/en

**Conclusion for 2a:** downloading TikTok video/audio by any automated means
outside an authorized, written-permission API integration is explicitly
prohibited — matching Instagram's posture almost clause-for-clause.

### 2b. Does a compliant official API path exist for this use case?

**No compliant commercial path exists.** TikTok's official developer
surfaces are:

- **Display API** — for embedding/showing TikTok videos in a third-party
  app (a distribution/embed use case, not a data-extraction one).
- **Content Posting API** — lets an authenticated user's app *post* videos
  to that same user's own TikTok account; it is a publishing tool, not a
  download tool.
- **Research API** — the one surface that does offer broader read access,
  but eligibility is explicitly restricted away from commercial products:

> Eligibility is limited to "qualifying academic institutions in the US,
> EEA, UK, and Switzerland, EU-registered non-profits, and Brazilian
> academic or non-profit researchers." … "Creators, advertisers, and
> commercial users are not eligible for Research Tools access," and
> "Research Tools cannot be used for any commercial or unauthorized
> purpose."
— https://developers.tiktok.com/products/research-api/ (via search-indexed snippet; direct fetch blocked, see sourcing note above)

Because Reel Vault is a commercial SaaS product, it is categorically
ineligible for the one TikTok API surface broad enough to plausibly cover
"fetch a video I don't own, by URL." The Display API and Content Posting
API don't offer the needed capability (arbitrary third-party video
download) at all, regardless of commercial status. **This mirrors
Instagram's Graph API gap: there is no official capability, at any price
tier, that does what Reel Vault needs for TikTok either.**

Where an app *does* have an authorized developer integration, the
Developer Terms restrict what can be done with the resulting data:

> "TikTok Information made available through the TikTok Developer Services
> may only be made available to End Users on a personal, non-exclusive,
> non-sublicensable, non-transferrable basis."
— https://www.tiktok.com/legal/page/global/tik-tok-developer-terms-of-service/en (via search-indexed snippet)

> Developers may not access the Developer Services "for any commercial or
> unauthorized purpose, including without limitation communicating or
> facilitating any commercial advertisement or solicitation or spamming."
— same URL (via search-indexed snippet)

**AMBIGUOUS — needs legal review:** whether "commercial or unauthorized
purpose" in that clause is read to exclude *any* paid SaaS built on
TikTok-derived data (Reel Vault's whole business model), or only excludes
things like ad-solicitation — the plain text is broad enough to support
either reading, and TikTok's own marketing simultaneously promotes
developer tools for building apps, so a lawyer's read (and likely direct
confirmation from TikTok's developer support) is needed rather than a
confident guess here.

### 2c. Explicit clauses on caching/long-term storage or redistributing derived data

> "Personal Data will not be kept for longer than necessary, subject to the
> terms and restrictions in the Developer Agreement and applicable law."
— TikTok Developer Data Sharing Agreement, https://www.tiktok.com/legal/page/global/tiktok-data-sharing-agreement/en (via search-indexed snippet)

> Upon termination: developers must "immediately cease use of any and all
> TikTok Developer Services, and delete TikTok Confidential Information or
> TikTok Information obtained through TikTok Developer Services in all forms
> in their possession and control (including from TikTok servers)."
— https://www.tiktok.com/legal/page/global/tik-tok-developer-terms-of-service/en (via search-indexed snippet)

No TikTok document found addresses AI-generated transcripts/summaries as a
named category, same silence as Instagram/Meta.

### 2d. Documented enforcement patterns

> "We may terminate or suspend your access to the Platform at any time,
> without prior notice or liability, for any reason whatsoever."
— https://www.tiktok.com/legal/page/row/terms-of-service/en (via search-indexed snippet)

> "TikTok may suspend or terminate some or all TikTok Developer Services at
> any time with or without notice, for any reason, without liability to the
> developer."
— https://www.tiktok.com/legal/page/global/tik-tok-developer-terms-of-service/en (via search-indexed snippet)

TikTok also publishes transparency data confirming automated detection is
the primary enforcement mechanism against violating content/accounts (not
merely a boilerplate clause — it's operationally how enforcement happens):

> "Automated removals, including those by AI, now make up more than 96
> percent of total removals" and TikTok's automated tools "actioned 93.8
> percent of all violating content without human review."
— https://www.tiktok.com/safety/en/policies-and-engagement/enforcement (via search-indexed snippet)

---

## 3. YouTube

### 3a. Automated access / scraping / downloading by third parties without the official API

**Explicitly prohibited**, and this is the most unambiguous, sharply-worded
of the three platforms. From the YouTube Terms of Service:

> Prohibited: to "access the Service using any automated means (such as
> robots, botnets or scrapers)" — except for public search engines
> following robots.txt, or with YouTube's prior written permission.
— https://www.youtube.com/static?template=terms ("Your Use of the Service")

> Prohibited: to "access, reproduce, download, distribute, transmit,
> broadcast, display, sell, license, alter, modify or otherwise use any part
> of the Service or any Content" without express authorization from YouTube
> and (as applicable) the relevant rights holders.
— same URL, same section

> Users may "view or listen to Content" only "for personal, non-commercial
> use (for example, you may not publicly screen videos or stream music from
> the Service)."
— same URL, same section

This directly forecloses exactly what Reel Vault does — download the video
file, and monetize a downstream product built on it — under the base
consumer Terms of Service alone, independent of the API terms below.

### 3b. Does a compliant official API path exist for this use case?

**No — the official API's own terms affirmatively prohibit this exact use
case,** in language even more specific than YouTube's consumer ToS. The
**YouTube API Services Terms of Service**
(https://developers.google.com/youtube/terms/api-services-terms-of-service)
states:

> "No rights or licenses are granted to reproduce or distribute audiovisual
> content or make audiovisual content available in any manner other than
> through the use of the YouTube API Services in accordance with the
> Agreement."
— same URL, Section 16.3

The companion **YouTube API Services Developer Policies**
(https://developers.google.com/youtube/terms/developer-policies) is even
more direct and is the single clearest "explicitly prohibited" clause found
across all three platforms for this exact use case:

> "You and your API Clients must not... download, import, backup, cache, or
> store copies of YouTube audiovisual content without YouTube's prior
> written approval."
— https://developers.google.com/youtube/terms/developer-policies, Section III.E.1.a

> "...make content available for offline playback"
— same URL, Section III.E.1.b

> "You and your API Clients must not... scrape YouTube Applications or
> Google Applications, or obtain scraped YouTube data or content."
— same URL, Section III.E.6

Reel Vault's transcription pipeline requires downloading and locally storing
the audio track of the video to run it through a transcription model — which
is precisely the conduct barred by III.E.1.a. There is no tier, quota, or
paid access level of the YouTube Data API v3 that lifts this prohibition;
it is a blanket "without YouTube's prior written approval" bar, not a
scraping-specific carve-out.

**Captions are not a workaround.** The API does expose a `captions.download`
endpoint, but it requires the requesting app to be authorized by the video's
own owner:

> `captions.download` "requires the user to have permission to edit the
> video" — OAuth scope `youtube.force-ssl` or `youtubepartner` — and returns
> HTTP 403 "The permissions associated with the request are not sufficient
> to download the caption track" if the caller is not the video's own
> channel.
— https://developers.google.com/youtube/v3/docs/captions/download

This means there is no official API path — video download *or* caption
download — that lets Reel Vault fetch transcript-equivalent data for a
Short uploaded by a channel unrelated to the app, which is the entire
Reel Vault use case (users share other creators' content).

### 3c. Explicit clauses on caching/long-term storage or redistributing derived data

The Developer Policies impose a hard numeric retention ceiling, and it is
explicit and dated (checked live, page last-updated per Google's own
revision history June 24 2026):

> "API Clients may temporarily store limited amounts of Non-Authorized Data
> ... but not longer than 30 calendar days." "API Clients may store all
> other types of Authorized Data ... for no longer than 30 calendar days.
> After 30 calendar days, the API Client must either delete or refresh the
> stored data."
— https://developers.google.com/youtube/terms/developer-policies, Sections III.E.4.c–d

There is a narrow carve-out for specific aggregate statistics (e.g. view
counts) that can be kept longer, contingent on periodic re-verification:

> API Clients "may store" certain statistics "for as long as is
> necessary... [but] must still ensure every 30 days that it is still
> authorized by the user to access that data."
— same URL, Section III.E.4.b

Derived/computed data is separately and explicitly restricted — directly
relevant to Reel Vault's plan to store AI-generated summaries rather than
raw transcripts long-term:

> API Clients "must not... replace API Data with similar, independently
> calculated data, or... access or use API Data to create new or derived
> data or metrics."
— same URL, Section III.E.4.h

**AMBIGUOUS — needs legal review:** whether an LLM-generated summary of a
transcript counts as "new or derived data or metrics" under III.E.4.h (which
reads most naturally as aimed at derived *analytics/metrics*, e.g.
recomputing engagement scores) or whether it is narrow enough to not cover a
prose summary for end-user search/retrieval. Given III.E.1.a already bars
downloading/caching the audiovisual content that a transcript would be
generated from in the first place, this second-order question may be moot
in practice — but a lawyer should confirm rather than assume the narrower
reading.

### 3d. Documented enforcement patterns

> YouTube reserves the right to "suspend or terminate your Google account or
> your access to all or part of the Service if: (a) you materially or
> repeatedly breach this Agreement."
— https://www.youtube.com/static?template=terms, "Account Suspension & Termination"

> "YouTube may set a quota on usage of any YouTube API Services at any time
> as applied to any specific YouTube API Services user or API Client."
— https://developers.google.com/youtube/terms/api-services-terms-of-service, Section 15

> "YouTube may monitor, review and inspect your API Client(s)... at any time
> and without further notice."
— same URL, Section 6 (audit rights)

> "YouTube reserves the right to suspend or terminate access to, or use of,
> any aspects of the YouTube API Services... at any time."
— same URL, Section 24.2

---

## Bottom line

| Platform | Non-API automated download | Official API path for this use case | Verdict |
|---|---|---|---|
| **Instagram / Meta** | Explicitly prohibited (Terms of Use + Automated Data Collection Terms, requires Meta's express written permission) | Graph API has no endpoint to fetch an arbitrary other user's Reel content at all — access is scoped to the authorizing account's own data, plus limited public hashtag search | **Clearly prohibited.** No official path exists for the described use case; even where Platform Data access exists, Meta Platform Terms bar selling/sharing it and require deletion once no longer needed for a legitimate business purpose. |
| **TikTok** | Explicitly prohibited (Terms of Service + Developer Terms of Service, requires TikTok's prior written permission) | Display API (embed only) and Content Posting API (post-your-own-video only) don't offer third-party video download; the one API broad enough (Research API) is contractually restricted to non-commercial academic/non-profit use and explicitly excludes commercial users | **Clearly prohibited.** No official, commercially-eligible path exists for the described use case. |
| **YouTube** | Explicitly prohibited (Terms of Service: no automated access, no download without authorization, personal-non-commercial-viewing only) | YouTube API Services Developer Policies explicitly bar downloading/caching/storing audiovisual content without YouTube's prior written approval, and separately cap any stored API data at 30 days; captions.download requires the video owner's own OAuth authorization, so it cannot be used for other creators' content either | **Clearly prohibited — the most explicit and specific prohibition of the three.** Both the video-download path and the captions-API path are closed for third-party content; the 30-day cache ceiling would also bar the intended cold-storage retention model even if content were otherwise obtainable. |

**No platform offers a clearly-permitted commercial path for Reel Vault's
download-and-transcribe model as currently designed.** All three explicitly
prohibit automated download of video/audio outside an authorized API
integration, and none of the three official APIs provide a capability (at
any commercial tier) to fetch arbitrary third-party video/audio content for
transcription. YouTube's prohibition is the most explicit and specific
(named "audiovisual content," named "cache," named "download," a numeric
30-day storage ceiling); Instagram/Meta's and TikTok's are broader
"automated means without permission" prohibitions that reach the same
conduct by a shorter path (there's no API capability to license in the
first place, so the permission gate can never be satisfied for this use
case).

Two points flagged **AMBIGUOUS — needs legal review** rather than resolved
by plain reading:
1. Whether AI-generated transcripts/summaries derived from platform content
   count as "Platform Data" (Meta) or "derived data" (YouTube, Section
   III.E.4.h) subject to the same restrictions as the raw content — none of
   the three platforms' documents name AI-generated derivative text as a
   distinct category.
2. Whether TikTok's "commercial or unauthorized purpose" developer
   restriction is read narrowly (excludes only things like ad solicitation)
   or broadly (excludes any paid SaaS built on TikTok data) — the text
   supports either reading.

Given the explicit, specific prohibitions found on all three platforms —
not silence, not ambiguity, but named "you must not download/cache/store...
without written approval" language — this is not primarily a "get a lawyer
to interpret gray text" situation for the *download-and-store* step itself.
It is closer to: the current architecture (fetch video by URL, download,
transcribe, store) is built on conduct that all three platforms' current
terms name and prohibit outright. The lawyer-needed items above are
narrower, second-order questions (how derived text is classified) that only
matter once/if the underlying download step is otherwise resolved (e.g. by
building on a licensed data provider, seeking direct platform partnership
agreements, or narrowing scope to platforms/methods not covered by this
research, such as a user manually uploading their own saved file rather
than the product fetching it from the source platform).
