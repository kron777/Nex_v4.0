# NEX Data Sources & Legal Compliance

## How NEX Uses External Sources

NEX does **not** reproduce, store, or redistribute source content.

Her belief extraction pipeline:
1. Fetches publicly accessible content
2. Extracts 1-3 individual sentences per article
3. Filters for epistemic claims (sentences containing verbs of reasoning)
4. Stores extracted sentences as discrete beliefs in a local SQLite database
5. Never stores full articles, paragraphs, or substantial portions of source text

This is a transformative use — extracted beliefs are derivative works,
not reproductions of source material.

---

## Sources

### ArXiv (arxiv.org)
- **License:** Open access — arXiv.org perpetual non-exclusive license
- **Commercial use:** Permitted for metadata and abstracts
- **How NEX uses it:** Extracts 1-3 sentences from paper abstracts only
- **Attribution:** Source tagged as `arxiv:category` in belief metadata
- **Legal notes:** ArXiv has explicitly supported AI research use of its corpus

### Wikipedia
- **License:** Creative Commons Attribution-ShareAlike 3.0 (CC BY-SA 3.0)
- **Commercial use:** Permitted with attribution and share-alike
- **How NEX uses it:** Extracts 1-3 sentences from article text
- **Attribution:** Source tagged as `wikipedia:ArticleName` in belief metadata
- **Legal notes:** CC BY-SA explicitly permits commercial use

### Stanford Encyclopedia of Philosophy (SEP)
- **License:** Copyright Metaphysics Research Lab, Stanford University
- **Commercial use:** Educational and research use explicitly permitted
- **How NEX uses it:** Extracts 1-3 sentences from entry text
- **Attribution:** Source tagged as `sep:slug` in belief metadata
- **Legal notes:** Non-reproductive extraction. Monitoring for commercial license
  requirements as NEX scales. Will replace with PhilArchive if required.

### LessWrong
- **License:** Creative Commons (varies by post)
- **Commercial use:** Generally permitted under CC terms
- **How NEX uses it:** Extracts 1-3 sentences from post excerpts via GraphQL API
- **Attribution:** Source tagged as `lesswrong:tag` in belief metadata

### PubMed / NCBI
- **License:** US Government funded — abstracts are public domain
- **Commercial use:** Explicitly permitted
- **How NEX uses it:** Extracts 1-3 sentences from abstracts only
- **Attribution:** Source tagged as `pubmed` in belief metadata
- **Legal notes:** NCBI explicitly encourages programmatic access

### Semantic Scholar
- **License:** Open Research Corpus — CC BY 4.0
- **Commercial use:** Explicitly permitted
- **How NEX uses it:** Extracts 1-3 sentences from paper abstracts
- **Attribution:** Source tagged as `semantic_scholar` in belief metadata

---

## What NEX Does NOT Do

- Does not store full articles or substantial portions of source text
- Does not reproduce copyrighted content in responses
- Does not cache or redistribute source material
- Does not scrape paywalled content
- Does not use news site content (high reproduction risk)
- Does not use copyrighted books (except Project Gutenberg public domain)

---

## Sources Being Evaluated / Avoided

| Source | Status | Reason |
|--------|--------|--------|
| News sites (NYT, Guardian etc.) | Avoided | High reproduction risk post-NYT v OpenAI |
| Paywalled academic journals | Avoided | Never crawled |
| Twitter/X | Avoided | ToS prohibits scraping |
| Copyrighted books | Avoided | Using Gutenberg public domain only |
| PhilArchive | Evaluating | More permissive than SEP |
| CORE.ac.uk | Evaluating | Explicitly permits AI use |

---

## Commercial Scale Plan

When NEX reaches commercial scale:
1. Obtain explicit commercial licenses for SEP content or replace with PhilArchive
2. Legal review of belief extraction pipeline by IP counsel
3. Implement full attribution tracking per belief
4. Publish transparency report on data sources and usage

---

## Contact

For licensing inquiries or data source concerns:
GitHub: github.com/kron777/Nex_v4.0

---

*Last updated: March 2026*
*NEX v4.0 — Dynamic Intelligence Organism*
