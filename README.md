# Bundesliga Coach Chatbot – Context Retrieval Script

This repository contains a Python script that acts as the context retrieval component for a hypothetical Retrieval-Augmented Generation (RAG) chatbot. The chatbot answers colloquial questions about the current head coaches of German 1. Bundesliga football clubs.

The script retrieves up-to-date information from **Wikidata** (via SPARQL) and **Wikipedia** (via the MediaWiki API) to construct a comprehensive prompt for a Large Language Model (LLM). The interface is entirely console-based.

## Features

- **Live Data Retrieval**: Queries Wikidata on startup to get the current list of 1. Bundesliga clubs, and queries Wikidata on every user question to get the most up-to-date head coach.
- **Wikipedia Integration**: Fetches the introductory biographical section of the coach's Wikipedia article to provide rich context.
- **Natural Language Parsing**: Uses regex patterns and fallback logic to extract city names or club aliases (e.g., "Pauli", "Gladbach", "Munich") from colloquial user questions.
- **Disambiguation**: Handles cases where multiple clubs exist in the same city (e.g., Hamburger SV and FC St. Pauli in Hamburg).
- **Robust Logging**: Implements both console logging for user feedback and detailed file logging (`chatbot_debug.log`) for debugging potential LLM hallucinations.

## Requirements

- Python 3.8+
- `requests` library

## Installation & Usage

1. Clone the repository and navigate to the directory.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the script:
   ```bash
   python bundesliga_chatbot.py
   ```
4. Enter your questions at the prompt. Examples:
   - "Who is coaching Berlin?"
   - "What about munich?"
   - "Who is heidenheims manager?"
   - "Who is it for Pauli?"

Type `quit` or `exit` to stop the script.

---

## Answers to Additional Questions

### 1. What are advantages and disadvantages of using additional information for a chatbot instead of letting the LLM answer without it?

**Advantages:**
- **Accuracy and Recency**: LLMs have a knowledge cutoff date. By injecting real-time data from Wikidata and Wikipedia, the chatbot can answer questions about recent managerial changes (which happen frequently in football) accurately.
- **Reduced Hallucination**: Providing explicit context grounds the LLM's response, significantly reducing the chance that it will invent a plausible-sounding but incorrect answer.
- **Traceability**: If the chatbot gives a wrong answer, developers can check the retrieved context (via logs) to determine if the error originated from the data source or the LLM's reasoning.

**Disadvantages:**
- **Latency**: Querying external APIs (Wikidata and Wikipedia) adds significant delay before the LLM can even begin generating a response.
- **Complexity and Points of Failure**: The system relies on external services. If Wikidata is down, rate-limited, or if the data schema changes, the chatbot will fail.
- **Cost**: While Wikipedia/Wikidata are free, in a commercial setting, making multiple API calls per user query can incur infrastructure costs.

### 2. What are advantages and disadvantages of querying for this data on every user question?

**Advantages:**
- **Absolute Freshness**: Football clubs can sack and hire managers on any given day. Querying on every question ensures the user always gets the coach who is in charge at that exact moment.
- **Statelessness**: The application does not need to maintain a complex caching or invalidation system for coach data, simplifying the architecture.

**Disadvantages:**
- **Performance Overhead**: Network requests take time (often 1-3 seconds for SPARQL queries), leading to a sluggish user experience.
- **API Rate Limiting**: Public APIs like Wikidata have strict usage limits. Querying on every question for a high-traffic chatbot would quickly result in IP bans or HTTP 429 (Too Many Requests) errors.
- **Redundancy**: Managerial changes, while frequent in a broader sense, do not happen every minute. Querying the same data repeatedly for different users is highly inefficient.

### 3. How would the process change if the information about coaches only were available via PDF?

If the data were only available in PDF format (e.g., a weekly press release from the DFL), the architecture would shift from a real-time API query model to an asynchronous ingestion pipeline:

1. **Data Ingestion**: A scheduled background job would download the PDF.
2. **Parsing and Extraction**: The system would need to use OCR or PDF parsing libraries (like `PyPDF2` or `pdfplumber`) to extract the text.
3. **Information Extraction (IE)**: We would likely need to use an LLM or specialized NLP models (Named Entity Recognition) to extract the structured relationships (Club -> City -> Coach) from the unstructured PDF text.
4. **Vector Database / Knowledge Graph**: The extracted data would be stored in a local database (SQL, NoSQL, or a Vector DB for semantic search).
5. **Retrieval**: At query time, the script would query this local database instead of Wikidata, drastically reducing latency but relying entirely on the accuracy of the PDF parsing step.

### 4. Do you see potential for agents in this process? If so, where and how?

Yes, autonomous agents could significantly enhance this process:

- **Query Routing Agent**: An agent could analyze the user's question to determine *which* data sources are needed. If a user asks "Who is the coach of Bayern?", it routes to the Wikidata tool. If they ask "What is the coach's tactical style?", it routes to a web search or Wikipedia tool.
- **Self-Healing SPARQL Agent**: Wikidata schemas can be complex and sometimes change. An agent could be given the schema and the goal, and if a SPARQL query fails or returns empty, the agent could dynamically rewrite the query to find the correct properties.
- **Disambiguation Agent**: Instead of hardcoding aliases (like "Pauli" -> "FC St. Pauli"), an agent could use an LLM to map colloquial user terms to official Wikidata entities dynamically.

### 5. How do these kinds of processes profit from a data model that models the specific domain knowledge?

A domain-specific data model (like an ontology or a Knowledge Graph specifically designed for football) provides immense benefits:

- **Semantic Relationships**: A domain model understands that a "Manager" and a "Head Coach" are semantically equivalent in this context, or that "Munich" is the city where "FC Bayern Munich" plays. This allows for much more flexible and intelligent querying.
- **Inference and Reasoning**: With a proper data model, the system can infer facts that aren't explicitly stated. For example, if the model knows that a coach was hired in 2024 and the current year is 2026, it can infer the coach's tenure length without needing a specific database field for it.
- **Scalability of Features**: If we later want the chatbot to answer questions about stadium capacities or team captains, a well-structured domain model (like Wikidata's property graph) allows us to simply traverse different edges (e.g., `P115` for home venue) without rewriting the entire application logic.
