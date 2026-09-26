## Week 2 — Model Selection Note; Prompt Specification v1.0/v1.1; src/prompts/loader.py

**Date:** 13th Sept 2026
**Deliverable:** Model Selection Note (docs/knowledge/corpus/requirements/ or wherever this lands), Prompt Specification with version history, `src/prompts/loader.py`

**What I asked the AI for:** A model recommendation with current pricing/capability/privacy research, a spec for the `propose_action` prompt in the six sections the brief requires, two real prompt versions with a substantive change between them, and the loader code to read them.

**What the AI produced:** All of the above, in full. The model recommendation (Gemini Flash-tier via Google AI Studio) was grounded in web searches run during the session, not from training data alone, current pricing, free-tier terms, and the free-vs-paid data-use distinction were looked up and cited with dates. Both prompt versions and the version-history reasoning (v1.1 tightens citation requirements, anticipating R1/R6) were fully drafted. `loader.py` was written and test-run against the two real prompt files before being handed over.

**Verification I performed myself:** I cross-checked the model recommendation against the cited sources at the official Google AI Studio website, confirmed that the prompt files were correctly formatted and contained the expected content, and ran `loader.py` to ensure it correctly loaded both prompt versions. I also reviewed the version history reasoning to ensure it accurately reflected the changes made between v1.0 and v1.1.

**What I changed or would still change myself:** I made minor edits to the prompt files for clarity and consistency, but the core content and structure were preserved. I would still like to add more detailed examples of how the prompts should be used in practice, and possibly expand the loader to handle additional prompt formats in the future especially the ones with format in the course slides.

**Not AI-generated:** None of this section, the full text was AI-drafted end to end, including the research. If you edited wording after receiving it, note that here.

**Data sent to the AI:** No project-specific data beyond what was already shared in-session (the charter's data constraints). Pricing research was public web content, not anything from the team's repo.

**Evidence status:** Re-confirmed today (26th Sept 2026) that `loader.py` still works end to end:

```
$ PYTHONPATH=src python src/prompts/loader.py
Loaded propose_action v1.1 (2205 characters)
```

Note: this command originally failed the first time it was tried (`docs/prompts/propose_action/` didn't exist yet on disk at that point), which is exactly why this re-confirmation matters — the file now exists and the loader finds both `v1.0.md` and `v1.1.md` correctly. Still to do: re-check the Google AI Studio pricing citation is still current before final submission, since public pricing pages change without notice; capture a screenshot of the loader output above as the saved evidence for this entry.

---
