We develop the service which allows to check if an LLM supports a specific language.

There are three basic scenarios:

1) User selects LLM. Question: what languages does this LLM support (list)?
2) User selects LLM and language. Question: does this LLM support this language?
3) User selects LLM, language and provides texts in English and selected language. Question: does this LLM support this language well enough?

Basic idea for algorithm: 
Step 1: translate English sample text to selected language. If LLM explicitly answers that it does not support - done.
Step 2: detect language with one or (if available) more expert LLMs. If none detects correctly, add 'unproven' flag to report.
Step 3: translate from selected language to English by selected LLM and by expert LLMs.
Step 4: Estimate fuzzy-match of initial phrase and translation. Compare selected LLM's translation to expert LLMs' translations.
Step 5: Report results.

Stage 1. Adding expert LLMs.
We have already a list of languages (around 600) and estimate support for ChatGPT-4o.
This LLM is initial expert LLM.
We run process against a few LLMs to check which languages they support, using ChatGPT-4o as an expert LLM.
Result: we get a few expert LLMs with support for variety of languages.

Stage 2: API for getting list of supported languages for LLMs which passed the expertize-check procedure.
Endpoint which gets list of supported languages by model name.
If model was not checked by stage-2 procedure, return 'Not evaluated yet'.

Stage 3. UI/API to check LLM against full list of languages.
User provides model name, endpoint and API kei (as password - encoded in UI) and starts the background process (queued?) to pass the procedure. Processed LLM is added to the server list.

Stage 4. UI and backend for scenario 2. 
User selects LLM or provides endpoint and API key and asks for specific language.
If selected LLM (means already in the DB) we simply return the answer (if language is in the server list). Otherwise we run the algorithm.
Next step: custom text to be used in the procedure.

Stage 5. UI and backend for scenario 3.
User selects LLM or provides endpoint and API key and asks for specific language. User also provide sample texts in both languages.
We run selected (or provided) LLM and expert LLMs in parallel to translate, then to detect language, then to translate back and fuzzy-match against provided translation sample. 
We compare fuzzy-matches for initial text in English and back-translated text from target language.
Note: we always check if text in target language is actually in claimed language. If not, we refuse the task.
Also, the source language may not be English, but any well-known language (Spanish, Russian, French or whatever alike).

Interface emphasize that this is not 100% proven or linguistically correct. This is only an empiric way to examine the LLM for specific languages.

Architecture:
SPA, microservices, docker compose, Redis for cache, RabbitMQ or Kafka for queues, OpenAI-v1 compatible only, Nginx or caddy (better to cover HTTPS).

Challenges:
1) Reduce expenses for LLM. We need to run the expert LLMs. How can we reduce the usage?
2) Reduce expenses for hosting. How can we reduce expenses for domain name, VPS and so on (infrastructure).
3) SMM and attractiveness.


Work in this order and stop for my confirmation between stages:

   1. Assumption check. Search if tools answering this question already exist—especially those with an API. If they do, say so directly: it changes the project's positioning. At the same time, check which open human translation datasets into a large number of languages are currently available and under what licenses.

   2. Methodology. Propose a specific evaluation scheme: what exactly we measure, which metrics we calculate, how the final result is formed, and how uncertainty is expressed. Challenge me if you see an error—but keeping in mind that I am building a tool, not a research paper.

   3. Architecture and cost estimation. Diagram, tech stack choice tailored to my profile, API cost calculations at different traffic levels, and a plan to prevent overspending.

   4. MVP implementation—step by step, with my review at each stage.

   5. README and page text with explicitly stated methodology and its limitations.

Do not start writing code until we agree on the methodology and architecture.

Ask clarifying questions if anything is missing.