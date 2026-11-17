# Independent reviewer 1

Reviewed working-tree SignalBrief follow-up implementation on 2026-11-17. No implementation edits. Review covered followup.js, followup.css, index.html integration, worker, service worker, specification and existing tests. No private access code files read.

## Finding 1 — P2: Existing follow-up sessions retain preliminary section content after evidence cross-check updates the analysis

References: followup.js:122–123; index.html:1118–1120; index.html:1420–1437.

Reproduction:
1. Run Evidence check with supporting sources.
2. When Claims and evidence becomes available but supporting-source cross-check is still pending, open Ask a follow-up for that card, then close it.
3. Let cross-check complete and replace the claims card with its evaluated content.
4. Reopen Ask a follow-up. Original section analysis still shows the preliminary content.
5. Submit a question. The request's section.text also contains the preliminary version.

Cause: session.section is initialized only when the session key is absent, while the analysis renderer replaces the contents under the same card ID. The original analysis on screen and the analysis supplied for research can disagree. Refresh section title/text from the current card each time it opens; decide explicitly whether prior answers should remain when the section changes.

Independent synthetic DOM reproduction succeeded: after replacing #sb-s2 body with `Corrected claims after cross-check`, both modal context and outbound request still read `Preliminary claims`.

## Minor usability observation — P3: Long new answers open at their end

Reference: followup.js:57.

renderAnswers always sets scrollTop to scrollHeight. Once the answer exceeds the cap, the first view is its end, typically the source list, rather than the opening findings. The first response should start at its beginning; subsequent responses could scroll the newly appended turn into view. This is a usability observation supported by code inspection, not an independently rendered visual defect.

## Verified behavior

Commands run with exit 0:
- `node --test tests/followup-worker.test.mjs`: 6 passed, 0 failed.
- `node /tmp/sb-review-1/review.cjs`: independent jsdom behavioral tests passed for completed-card enhancement, pending-card exclusion, initial question focus, close-button focus restoration, draft restoration, no-evidence request, safe clickable citation links, canceled late response suppression, and clearing history. Also reproduced Finding 1 with assertions.
- `node /tmp/sb-review-1/evidence.cjs`: independent jsdom tests passed for valid text evidence, invalid extension rejection preserving prior attachments, evidence removal, 4 MiB rejection, 120,000-character rejection, and re-enabled retry control.

Static review: native dialog has an accessible title and Escape handler; fields are labeled; response region is keyboard focusable; file remove controls have descriptive names; native dialog provides browser focus containment. CSS uses existing colors and IBM Plex font families, natural answer height, maximum height, overflow-y:auto, mobile width rules and reduced-motion support. Frontend inserts answer/evidence content as text, and filters citation schemes. Backend enforces authentication and allowed browser origin, attachment limits, generic public research instructions, high reasoning, forced web search and annotation-derived citations. Existing analysis endpoint behavior has a passing regression test.

## Limits / release gate

I did not perform real-browser visual/mobile/scrollbar checks or an authenticated live OpenAI request. The coordinator owns those checks. jsdom cannot validate rendered geometry, native dialog focus trapping, browser Escape behavior, mobile layout or actual research quality. Worker tests mock OpenAI; they verify request/response behavior, not that the selected production model currently supports all parameters. Do not treat this report as proof of deployed or visually validated behavior. Finding 1 should be resolved before release.
