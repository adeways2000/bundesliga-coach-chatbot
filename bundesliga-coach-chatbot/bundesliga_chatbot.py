#!/usr/bin/env python3
"""
Context Retrieval Script for a RAG-Chatbot about Bundesliga Football Clubs.

This script retrieves information about the current head coaches of German
1. Bundesliga football clubs using Wikidata (SPARQL) and Wikipedia APIs.
It processes user questions about coaches of specific cities and constructs
a prompt suitable for a Large Language Model (LLM).

Usage:
    python bundesliga_chatbot.py

The script runs an interactive console loop where users can ask questions like:
    - "Who is coaching Berlin?"
    - "What about munich?"
    - "Who is heidenheims manager?"
    - "Who is it for Pauli?"
"""

import logging
import re
import sys
import json
from typing import Optional, Dict, List
from urllib.parse import unquote

import requests

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
# Two handlers are configured:
#   1. Console handler (INFO level) – for user-facing status messages.
#   2. File handler (DEBUG level) – for detailed debugging of data retrieval,
#      which is essential for tracing potential false answers from the LLM.

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("bundesliga_chatbot")
logger.setLevel(logging.DEBUG)

# Console handler – shows INFO and above to the user
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
logger.addHandler(console_handler)

# File handler – captures DEBUG and above for post-mortem analysis
file_handler = logging.FileHandler("chatbot_debug.log", mode="a", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
logger.addHandler(file_handler)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIPEDIA_API_ENDPOINT = "https://en.wikipedia.org/w/api.php"

# User-Agent header required by Wikimedia API policy
USER_AGENT = (
    "BundesligaCoachChatbot/1.0 "
    "(https://github.com/example/bundesliga-coach-chatbot; "
    "contact@example.com) Python/3 requests"
)

# ---------------------------------------------------------------------------
# SPARQL Queries
# ---------------------------------------------------------------------------

# Query to retrieve all clubs currently in the 1. Bundesliga (via P118),
# along with their city (P159), head coach (P286), and the coach's English
# Wikipedia article title. This uses the "league" property which Wikidata
# maintains on the main club entity to indicate current league membership.
SPARQL_CURRENT_BUNDESLIGA_CLUBS = """
SELECT ?club ?clubLabel ?city ?cityLabel ?coach ?coachLabel ?coachArticle WHERE {
  ?club wdt:P118 wd:Q82595 .       # club's league is Bundesliga
  ?club wdt:P286 ?coach .           # club has a head coach
  ?club wdt:P159 ?city .            # club's headquarters location (city)
  OPTIONAL {
    ?coachArticle schema:about ?coach ;
                  schema:isPartOf <https://en.wikipedia.org/> .
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,de" . }
}
"""

# Query to retrieve the head coach of a specific club by its Wikidata QID.
# This is used on every user question to ensure coach data is always fresh.
SPARQL_COACH_FOR_CLUB = """
SELECT ?coach ?coachLabel ?coachArticle WHERE {{
  wd:{club_qid} wdt:P286 ?coach .
  OPTIONAL {{
    ?coachArticle schema:about ?coach ;
                  schema:isPartOf <https://en.wikipedia.org/> .
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,de" . }}
}}
"""

# Wikidata QIDs to exclude from results (e.g., women's teams or non-standard
# entities that happen to share the P118 = Bundesliga property).
EXCLUDED_CLUB_QIDS = {
    "Q162449",     # 1. FFC Frankfurt (women's football club)
    "Q28854979",   # Hertha BSC – current squad (non-standard entity)
}

# Manual mapping for clubs whose Wikidata entities are non-standard.
# For example, Hertha BSC's "current squad" entity (Q28854979) has P118
# but the main club entity is Q160149.
CLUB_QID_OVERRIDES = {
    # If Hertha BSC appears via a non-standard entity, map to the main one
    "Q28854979": "Q160149",  # Hertha BSC – current squad -> Hertha BSC
}


# ---------------------------------------------------------------------------
# Data Retrieval: Wikidata
# ---------------------------------------------------------------------------

def query_wikidata(sparql: str) -> Optional[List[Dict]]:
    """
    Execute a SPARQL query against the Wikidata Query Service.

    Args:
        sparql: The SPARQL query string.

    Returns:
        A list of result bindings (dicts) on success, or None on failure.
    """
    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": USER_AGENT,
    }
    params = {"query": sparql, "format": "json"}

    logger.debug("Sending SPARQL query to Wikidata:\n%s", sparql.strip()[:300])

    try:
        response = requests.get(
            WIKIDATA_SPARQL_ENDPOINT,
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        logger.debug("Wikidata returned %d result(s).", len(bindings))
        return bindings

    except requests.exceptions.Timeout:
        logger.error("Wikidata query timed out after 30 seconds.")
        return None
    except requests.exceptions.HTTPError as exc:
        logger.error("Wikidata HTTP error: %s", exc)
        return None
    except requests.exceptions.RequestException as exc:
        logger.error("Wikidata request failed: %s", exc)
        return None
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse Wikidata response: %s", exc)
        return None


def _extract_qid(uri: str) -> str:
    """Extract the QID (e.g., 'Q15789') from a Wikidata entity URI."""
    return uri.split("/")[-1] if uri else ""


def _extract_wiki_title(article_url: str) -> str:
    """Extract and URL-decode the Wikipedia article title from a full URL."""
    if article_url and "/wiki/" in article_url:
        return unquote(article_url.split("/wiki/")[-1])
    return ""


def fetch_current_bundesliga_clubs() -> Optional[List[Dict]]:
    """
    Retrieve all clubs currently in the 1. Bundesliga along with their
    city, head coach, and the coach's Wikipedia article title.

    The query uses P118 (league) to find clubs whose current league is
    the Bundesliga (Q82595). This is maintained by Wikidata editors and
    reflects the current season's participants.

    Returns:
        A list of dicts with keys: club_qid, club_name, city_name,
        coach_qid, coach_name, coach_wiki_title.  Returns None on failure.
    """
    bindings = query_wikidata(SPARQL_CURRENT_BUNDESLIGA_CLUBS)
    if bindings is None:
        return None

    teams = []
    seen_clubs = set()  # Avoid duplicates

    for b in bindings:
        club_qid = _extract_qid(b.get("club", {}).get("value", ""))

        # Skip excluded entities (women's teams, non-standard entities)
        if club_qid in EXCLUDED_CLUB_QIDS:
            logger.debug("Skipping excluded entity: %s", club_qid)
            continue

        # Apply QID overrides if needed
        if club_qid in CLUB_QID_OVERRIDES:
            club_qid = CLUB_QID_OVERRIDES[club_qid]

        # Skip duplicates
        if club_qid in seen_clubs:
            continue
        seen_clubs.add(club_qid)

        club_name = b.get("clubLabel", {}).get("value", "")
        city_name = b.get("cityLabel", {}).get("value", "")
        coach_qid = _extract_qid(b.get("coach", {}).get("value", ""))
        coach_name = b.get("coachLabel", {}).get("value", "")
        coach_wiki_title = _extract_wiki_title(
            b.get("coachArticle", {}).get("value", "")
        )

        teams.append({
            "club_qid": club_qid,
            "club_name": club_name,
            "city_name": city_name,
            "coach_qid": coach_qid,
            "coach_name": coach_name,
            "coach_wiki_title": coach_wiki_title,
        })

    logger.debug("Parsed %d team entries from Wikidata.", len(teams))
    return teams


def fetch_coach_for_club(club_qid: str) -> Optional[Dict]:
    """
    Retrieve the current head coach for a specific club (by Wikidata QID).

    This is called on every user question to ensure the coach information
    is always up-to-date, as required by the challenge specification.

    Args:
        club_qid: The Wikidata QID of the club (e.g., "Q15789").

    Returns:
        A dict with keys: coach_qid, coach_name, coach_wiki_title.
        Returns None on failure.
    """
    sparql = SPARQL_COACH_FOR_CLUB.format(club_qid=club_qid)
    bindings = query_wikidata(sparql)
    if not bindings:
        return None

    # Take the first result (a club should have one current head coach)
    b = bindings[0]
    coach_qid = _extract_qid(b.get("coach", {}).get("value", ""))
    coach_name = b.get("coachLabel", {}).get("value", "")
    coach_wiki_title = _extract_wiki_title(
        b.get("coachArticle", {}).get("value", "")
    )

    return {
        "coach_qid": coach_qid,
        "coach_name": coach_name,
        "coach_wiki_title": coach_wiki_title,
    }


# ---------------------------------------------------------------------------
# Data Retrieval: Wikipedia
# ---------------------------------------------------------------------------

def fetch_wikipedia_intro(title: str) -> Optional[str]:
    """
    Retrieve the introductory section of a Wikipedia article.

    Uses the Wikipedia API's "extracts" module to get a plain-text summary
    of the article's lead section. This provides biographical context about
    the coach that can be included in the LLM prompt.

    Args:
        title: The Wikipedia article title (e.g., "Vincent_Kompany").

    Returns:
        The plain-text intro string, or None on failure.
    """
    if not title:
        logger.warning("No Wikipedia article title provided; skipping intro fetch.")
        return None

    params = {
        "action": "query",
        "titles": title,
        "prop": "extracts",
        "exintro": True,        # Only the intro section
        "explaintext": True,    # Plain text, no HTML
        "format": "json",
        "redirects": 1,         # Follow redirects
    }
    headers = {"User-Agent": USER_AGENT}

    logger.debug("Fetching Wikipedia intro for article: '%s'", title)

    try:
        response = requests.get(
            WIKIPEDIA_API_ENDPOINT,
            headers=headers,
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        pages = data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if page_id == "-1":
                logger.warning("Wikipedia article '%s' not found.", title)
                return None
            extract = page_data.get("extract", "")
            if extract:
                logger.debug(
                    "Retrieved Wikipedia intro for '%s' (%d characters).",
                    title, len(extract),
                )
                return extract.strip()

        logger.warning("No extract found for Wikipedia article '%s'.", title)
        return None

    except requests.exceptions.RequestException as exc:
        logger.error("Wikipedia request failed for '%s': %s", title, exc)
        return None
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse Wikipedia response for '%s': %s", title, exc)
        return None


# ---------------------------------------------------------------------------
# City-to-Club Mapping
# ---------------------------------------------------------------------------

class BundesligaTeamRegistry:
    """
    Maintains a mapping from city names (and special aliases like "Pauli")
    to Bundesliga club information.

    The mapping is built from Wikidata on initialization and cached for the
    lifetime of the application. The actual coach data is always fetched
    fresh from Wikidata on each user query.
    """

    def __init__(self):
        self._city_map: Dict[str, List[Dict]] = {}
        self._alias_map: Dict[str, str] = {}
        self._loaded = False

    def load(self) -> bool:
        """
        Load the current Bundesliga clubs from Wikidata and build the
        city-to-club lookup mapping.

        Returns:
            True if loading succeeded, False otherwise.
        """
        logger.info("Loading current Bundesliga club data from Wikidata...")
        teams = fetch_current_bundesliga_clubs()
        if teams is None or len(teams) == 0:
            logger.error("Failed to load Bundesliga team data from Wikidata.")
            return False

        self._city_map.clear()
        self._alias_map.clear()

        for team in teams:
            city_lower = team["city_name"].lower()

            # Map by city name
            if city_lower not in self._city_map:
                self._city_map[city_lower] = []
            self._city_map[city_lower].append(team)

            # Build special aliases for this club
            self._register_aliases(team)

        self._loaded = True
        logger.info(
            "Loaded %d teams across %d cities.",
            sum(len(v) for v in self._city_map.values()),
            len(self._city_map),
        )
        logger.debug("City map keys: %s", list(self._city_map.keys()))
        logger.debug("Alias map: %s", dict(self._alias_map))
        return True

    def _register_aliases(self, team: Dict):
        """
        Register additional lookup aliases for a team based on its club name.

        This handles cases like:
        - "St. Pauli" / "Pauli" for FC St. Pauli
        - "Heidenheim" for 1. FC Heidenheim 1846
        - "Gladbach" for Borussia Mönchengladbach
        - "Munich" / "München" for FC Bayern Munich
        """
        club_name = team["club_name"]
        club_lower = club_name.lower()
        city_lower = team["city_name"].lower()

        # --- FC St. Pauli ---
        if "pauli" in club_lower:
            self._alias_map["pauli"] = ("hamburg", club_lower)
            self._alias_map["st. pauli"] = ("hamburg", club_lower)
            self._alias_map["st pauli"] = ("hamburg", club_lower)

        # --- Heidenheim ---
        if "heidenheim" in club_lower:
            self._alias_map["heidenheim"] = (city_lower, None)

        # --- Gladbach / Mönchengladbach ---
        if "mönchengladbach" in club_lower or "gladbach" in club_lower:
            self._alias_map["gladbach"] = (city_lower, None)
            self._alias_map["mönchengladbach"] = (city_lower, None)
            self._alias_map["monchengladbach"] = (city_lower, None)

        # --- Köln / Cologne ---
        if "köln" in club_lower or "cologne" in city_lower.lower():
            self._alias_map["köln"] = (city_lower, None)
            self._alias_map["koln"] = (city_lower, None)
            self._alias_map["cologne"] = (city_lower, None)

        # --- München / Munich ---
        if "münchen" in club_lower or "munich" in club_lower or "bayern" in club_lower:
            self._alias_map["münchen"] = (city_lower, None)
            self._alias_map["munchen"] = (city_lower, None)
            self._alias_map["munich"] = (city_lower, None)

        # --- Nürnberg / Nuremberg ---
        if "nürnberg" in club_lower or "nuremberg" in city_lower.lower():
            self._alias_map["nürnberg"] = (city_lower, None)
            self._alias_map["nurnberg"] = (city_lower, None)
            self._alias_map["nuremberg"] = (city_lower, None)

        # --- Düsseldorf ---
        if "düsseldorf" in club_lower or "düsseldorf" in city_lower:
            self._alias_map["düsseldorf"] = (city_lower, None)
            self._alias_map["dusseldorf"] = (city_lower, None)

        # --- Common city-based aliases from club names ---
        # Extract city-like tokens that might differ from the P159 city
        city_aliases = {
            "leverkusen": "leverkusen",
            "wolfsburg": "wolfsburg",
            "hoffenheim": "sinsheim",
            "dortmund": "dortmund",
            "bremen": "bremen",
            "frankfurt": "frankfurt",
            "freiburg": "freiburg im breisgau",
            "berlin": "berlin",
            "leipzig": "leipzig",
            "stuttgart": "stuttgart",
            "mainz": "mainz",
            "augsburg": "augsburg",
            "bochum": "bochum",
            "hamburg": "hamburg",
            "paderborn": "paderborn",
            "hannover": "hannover",
        }
        for alias, target_city in city_aliases.items():
            if alias in club_lower and alias not in self._city_map:
                if alias != city_lower:
                    self._alias_map[alias] = (city_lower, None)

        # Also add "hoffenheim" as alias for the Sinsheim-based club
        if "hoffenheim" in club_lower:
            self._alias_map["hoffenheim"] = (city_lower, None)

    def find_clubs_for_query(self, query_term: str) -> List[Dict]:
        """
        Find clubs matching a query term (city name or alias).

        The lookup is case-insensitive. It checks:
        1. Direct city match
        2. Alias match (with optional club-specific disambiguation)
        3. Partial/substring match

        Args:
            query_term: The city name or alias extracted from the user question.

        Returns:
            A list of matching team dicts (may be empty).
        """
        if not self._loaded:
            logger.error("Team registry not loaded. Call load() first.")
            return []

        term = query_term.strip().lower()
        logger.debug("Looking up clubs for query term: '%s'", term)

        # 1. Direct city match
        if term in self._city_map:
            logger.debug("Direct city match found for '%s'.", term)
            return self._city_map[term]

        # 2. Alias match
        if term in self._alias_map:
            city_key, specific_club = self._alias_map[term]
            logger.debug("Alias match: '%s' -> city '%s', club filter '%s'.",
                         term, city_key, specific_club)
            clubs = self._city_map.get(city_key, [])
            if specific_club:
                # Filter to the specific club (e.g., "Pauli" -> FC St. Pauli only)
                filtered = [c for c in clubs if specific_club in c["club_name"].lower()]
                if filtered:
                    return filtered
            return clubs

        # 3. Partial match on city names
        for city_key, clubs in self._city_map.items():
            if term in city_key or city_key.startswith(term):
                logger.debug("Partial city match: '%s' in '%s'.", term, city_key)
                return clubs

        # 4. Partial match on alias keys
        for alias_key, (city_key, specific_club) in self._alias_map.items():
            if term in alias_key or alias_key.startswith(term):
                logger.debug("Partial alias match: '%s' in '%s'.", term, alias_key)
                clubs = self._city_map.get(city_key, [])
                if specific_club:
                    filtered = [c for c in clubs if specific_club in c["club_name"].lower()]
                    if filtered:
                        return filtered
                return clubs

        logger.warning("No club found for query term: '%s'.", term)
        return []


# ---------------------------------------------------------------------------
# User Query Parsing
# ---------------------------------------------------------------------------

def extract_city_from_question(question: str) -> Optional[str]:
    """
    Extract the city name or club identifier from a user's natural language
    question about a Bundesliga coach.

    Handles various colloquial phrasings such as:
    - "Who is coaching Berlin?"
    - "What about munich?"
    - "Who is heidenheims manager?"
    - "Who is it for Pauli?"

    Args:
        question: The raw user question string.

    Returns:
        The extracted city/club identifier, or None if no match is found.
    """
    # Clean up the question: strip whitespace and trailing punctuation
    q = question.strip().rstrip("?!.").strip()

    # Regex patterns ordered from most specific to most general.
    # Each pattern captures the city/club name in group 1.
    patterns = [
        # "Who is coaching Berlin"
        r"(?i)who\s+is\s+coaching\s+(.+)",
        # "Who is the coach/manager/trainer of Berlin"
        r"(?i)who\s+is\s+the\s+(?:coach|manager|trainer|head\s*coach)\s+(?:of|for|in)\s+(.+)",
        # "Who is Berlin's coach/manager" (with apostrophe)
        r"(?i)who\s+is\s+(.+?)'s\s+(?:coach|manager|trainer|head\s*coach)",
        # "Who is heidenheims manager" (possessive without apostrophe)
        r"(?i)who\s+is\s+(.+?)s\s+(?:coach|manager|trainer|head\s*coach)",
        # "Who coaches Berlin"
        r"(?i)who\s+coaches\s+(.+)",
        # "What about munich"
        r"(?i)what\s+about\s+(.+)",
        # "Who is it for Pauli"
        r"(?i)who\s+is\s+it\s+for\s+(.+)",
        # "Tell me about the coach of Berlin"
        r"(?i)tell\s+me\s+about\s+(?:the\s+)?(?:coach|manager|trainer)\s+(?:of|for|in)\s+(.+)",
        # "Coach of Berlin" / "Manager of Berlin"
        r"(?i)(?:coach|manager|trainer)\s+(?:of|for|in)\s+(.+)",
        # Fallback: anything after coaching/coach/manager/trainer/about/for
        r"(?i)(?:coaching|coach|manager|trainer|about|for)\s+(.+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, q)
        if match:
            city = match.group(1).strip().rstrip("?!.").strip()
            if city:
                logger.debug(
                    "Extracted city '%s' from question using pattern: %s",
                    city, pattern,
                )
                return city

    # Ultimate fallback: return the last non-stop word in the question
    stop_words = {
        "who", "is", "the", "a", "an", "of", "for", "in", "it",
        "what", "about", "coaching", "coach", "manager", "trainer",
        "tell", "me", "head", "current", "new",
    }
    words = q.split()
    for word in reversed(words):
        clean_word = word.strip("?!.,").lower()
        if clean_word and clean_word not in stop_words:
            logger.debug("Fallback extraction: '%s' from question.", word.strip("?!.,"))
            return word.strip("?!.,")

    logger.warning("Could not extract a city name from question: '%s'", question)
    return None


# ---------------------------------------------------------------------------
# Prompt Construction
# ---------------------------------------------------------------------------

# System prompt that instructs the LLM on how to behave
SYSTEM_PROMPT = (
    "You are a knowledgeable assistant specializing in German football (soccer). "
    "Your role is to answer questions about the current head coaches of clubs in "
    "the German 1. Bundesliga.\n\n"
    "When answering:\n"
    "- Provide the name of the current head coach.\n"
    "- Include a brief biographical summary of the coach.\n"
    "- Mention the club they are coaching and the city.\n"
    "- Be concise but informative.\n"
    "- If the provided context does not contain enough information, say so honestly.\n\n"
    "Use ONLY the provided context information to answer. Do not make up information."
)


def build_llm_prompt(
    user_question: str,
    club_name: str,
    city_name: str,
    coach_name: str,
    coach_bio: Optional[str],
) -> str:
    """
    Construct the final prompt string for the LLM.

    The prompt follows a standard RAG pattern with three sections:
    1. System prompt – defines the LLM's role and behaviour.
    2. Context – the retrieved factual information from Wikidata and Wikipedia.
    3. User question – the original question from the user.

    Args:
        user_question: The original user question.
        club_name: The name of the Bundesliga club.
        city_name: The city where the club is based.
        coach_name: The name of the current head coach.
        coach_bio: The introductory text from the coach's Wikipedia article.

    Returns:
        A formatted prompt string ready for LLM consumption.
    """
    # Build the context section from retrieved data
    context_parts = [
        f"Club: {club_name}",
        f"City: {city_name}",
        f"Current Head Coach: {coach_name}",
    ]

    if coach_bio:
        context_parts.append(
            f"\nBiographical information about {coach_name}:\n{coach_bio}"
        )
    else:
        context_parts.append(
            f"\nNote: No biographical information was found for "
            f"{coach_name} on Wikipedia."
        )

    context_block = "\n".join(context_parts)

    # Assemble the full prompt with clear section delimiters
    prompt = (
        f"=== SYSTEM PROMPT ===\n"
        f"{SYSTEM_PROMPT}\n\n"
        f"=== RETRIEVED CONTEXT ===\n"
        f"{context_block}\n\n"
        f"=== USER QUESTION ===\n"
        f"{user_question}\n"
    )

    return prompt


def build_disambiguation_message(
    user_question: str,
    clubs: List[Dict],
) -> str:
    """
    Build a message when multiple clubs match the user's query (e.g., two
    clubs in the same city like Hamburg).

    Args:
        user_question: The original user question.
        clubs: List of matching club dicts.

    Returns:
        A formatted message asking the user to clarify.
    """
    club_list = "\n".join(
        f"  - {club['club_name']} ({club['city_name']})"
        for club in clubs
    )
    return (
        f"Multiple clubs found matching your query:\n{club_list}\n\n"
        f"Please specify which club you mean. For example, you can use "
        f"'Pauli' for FC St. Pauli, or 'Hamburg' for Hamburger SV."
    )


# ---------------------------------------------------------------------------
# Main Application Logic
# ---------------------------------------------------------------------------

def process_question(question: str, registry: BundesligaTeamRegistry) -> str:
    """
    Process a single user question and return the constructed LLM prompt
    or an informative error/disambiguation message.

    This is the core orchestration function that:
    1. Parses the user question to extract the city/club identifier.
    2. Looks up the club in the registry.
    3. Fetches the current coach from Wikidata (fresh on every question).
    4. Fetches the coach's Wikipedia bio (fresh on every question).
    5. Builds and returns the LLM prompt.

    Args:
        question: The user's natural language question.
        registry: The loaded BundesligaTeamRegistry.

    Returns:
        The constructed LLM prompt string, or an error/disambiguation message.
    """
    logger.info("Processing question: '%s'", question)

    # Step 1: Extract the city or club identifier from the question
    city_term = extract_city_from_question(question)
    if not city_term:
        msg = (
            "I could not understand which city or club you are asking about. "
            "Please try rephrasing your question, for example: "
            "'Who is coaching Berlin?' or 'What about Munich?'"
        )
        logger.warning("City extraction failed for: '%s'", question)
        return msg

    logger.info("Extracted search term: '%s'", city_term)

    # Step 2: Look up the club(s) in the registry
    matching_clubs = registry.find_clubs_for_query(city_term)

    if not matching_clubs:
        msg = (
            f"I could not find a 1. Bundesliga club associated with "
            f"'{city_term}'. Please check the city name and try again. "
            f"Note: Only clubs in the current 1. Bundesliga season are "
            f"supported."
        )
        logger.warning("No club found for term: '%s'", city_term)
        return msg

    # Step 3: Handle disambiguation if multiple clubs match
    if len(matching_clubs) > 1:
        logger.info(
            "Multiple clubs found for '%s': %s",
            city_term,
            [c["club_name"] for c in matching_clubs],
        )
        return build_disambiguation_message(question, matching_clubs)

    club = matching_clubs[0]
    logger.info(
        "Matched club: %s (QID: %s, City: %s)",
        club["club_name"], club["club_qid"], club["city_name"],
    )

    # Step 4: Fetch the current coach from Wikidata (fresh query every time)
    logger.info(
        "Fetching current coach for %s from Wikidata...", club["club_name"]
    )
    coach_data = fetch_coach_for_club(club["club_qid"])

    if coach_data is None:
        msg = (
            f"I found the club {club['club_name']} in {club['city_name']}, "
            f"but could not retrieve the current coach information from "
            f"Wikidata. This might be a temporary issue – please try again."
        )
        logger.error("Failed to fetch coach for club %s.", club["club_name"])
        return msg

    coach_name = coach_data["coach_name"]
    coach_wiki_title = coach_data["coach_wiki_title"]

    logger.info("Current coach: %s (Wikipedia: '%s')", coach_name, coach_wiki_title)
    logger.debug(
        "Coach data from Wikidata: QID=%s, Name=%s, WikiTitle=%s",
        coach_data["coach_qid"], coach_name, coach_wiki_title,
    )

    # Step 5: Fetch the coach's Wikipedia biography (fresh query every time)
    logger.info("Fetching Wikipedia biography for %s...", coach_name)
    coach_bio = fetch_wikipedia_intro(coach_wiki_title)

    if coach_bio:
        logger.info(
            "Retrieved biography for %s (%d characters).",
            coach_name, len(coach_bio),
        )
        logger.debug("Biography excerpt: %s...", coach_bio[:200])
    else:
        logger.warning(
            "No Wikipedia biography found for %s. "
            "The prompt will note this gap.", coach_name,
        )

    # Step 6: Build and return the LLM prompt
    prompt = build_llm_prompt(
        user_question=question,
        club_name=club["club_name"],
        city_name=club["city_name"],
        coach_name=coach_name,
        coach_bio=coach_bio,
    )

    logger.debug("Constructed LLM prompt (%d characters).", len(prompt))
    return prompt


def main():
    """
    Main entry point. Runs an interactive console loop where the user can
    ask questions about Bundesliga coaches.
    """
    print("=" * 70)
    print("  Bundesliga Coach Chatbot – Context Retrieval System")
    print("=" * 70)
    print()
    print("This tool retrieves information about the current head coaches")
    print("of German 1. Bundesliga football clubs and constructs a prompt")
    print("for a Large Language Model (LLM).")
    print()
    print("Example questions:")
    print('  - "Who is coaching Berlin?"')
    print('  - "What about munich?"')
    print('  - "Who is heidenheims manager?"')
    print('  - "Who is it for Pauli?"')
    print()
    print('Type "quit" or "exit" to stop.')
    print("=" * 70)
    print()

    # Initialize and load the team registry
    registry = BundesligaTeamRegistry()
    if not registry.load():
        print(
            "\nERROR: Could not load Bundesliga team data from Wikidata.\n"
            "Please check your internet connection and try again."
        )
        sys.exit(1)

    print("\nReady! Ask me about a Bundesliga coach.\n")

    # Interactive loop
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        # Process the question and display the result
        result = process_question(user_input, registry)

        print("\n" + "-" * 70)
        print("GENERATED LLM PROMPT:")
        print("-" * 70)
        print(result)
        print("-" * 70 + "\n")


if __name__ == "__main__":
    main()
