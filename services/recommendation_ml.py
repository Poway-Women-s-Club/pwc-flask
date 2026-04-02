"""
Content-based recommendations using TF–IDF vectors and cosine similarity.

This is standard information-retrieval / ML: represent the member profile and each
group/event as bags of weighted terms, then rank by cosine similarity between the
profile vector and each candidate. No external APIs; works offline.

Optional interest-phrase boost rewards when a full interest string appears in the text.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable, List, Sequence, Tuple

# Compact English stop list — enough for short club bios/descriptions.
_STOP = frozenset(
    """
    a an the and or but if as at by for from in into is it its of on to with
    all any both each few more most other some such than that these this those
    am are was were be been being have has had having do does did doing will would
    could should may might must shall can about above after again against before
    being below between during under until while here there when where why how
    who which what whom whose not no nor too very just own same so than too very
    s t don doesn didn wasn weren won weren re ll ve d m o
    """.split()
)


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    raw = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for t in raw:
        if len(t) < 2 or t in _STOP:
            continue
        out.append(t)
    return out


def _document_frequency(token_lists: Sequence[Sequence[str]]) -> Counter:
    df: Counter = Counter()
    for tokens in token_lists:
        for w in set(tokens):
            df[w] += 1
    return df


def _tfidf_vector(tokens: List[str], df: Counter, n_docs: int) -> dict:
    tf = Counter(tokens)
    vec: dict = {}
    for w, c in tf.items():
        dfi = df.get(w, 0)
        idf = math.log((n_docs + 1) / (dfi + 1)) + 1.0
        vec[w] = float(c) * idf
    return vec


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def _overlap_terms(user_vec: dict, item_vec: dict, limit: int = 6) -> List[str]:
    """Terms that appear in both vectors, sorted by contribution to dot product."""
    common = set(user_vec) & set(item_vec)
    scored = [(user_vec[w] * item_vec[w], w) for w in common]
    scored.sort(reverse=True)
    return [w for _, w in scored[:limit]]


def _interest_boost(interests: Iterable[str], languages: Iterable[str], doc_text: str) -> float:
    """Small additive boost for exact interest / language phrases in the document."""
    hay = doc_text.lower()
    bonus = 0.0
    for phrase in interests:
        p = (phrase or "").strip().lower()
        if len(p) >= 3 and p in hay:
            bonus += 0.12
    for lang in languages:
        p = (lang or "").strip().lower()
        if len(p) >= 3 and p in hay:
            bonus += 0.08
    return min(bonus, 0.5)


def _build_user_profile_text(bio: str, interests: Sequence[str], languages: Sequence[str]) -> str:
    parts = [bio or ""]
    parts.append(" ".join(interests or []))
    parts.append(" ".join(languages or []))
    return "\n".join(p for p in parts if p)


def recommend_groups_events(
    bio: str,
    interests: Sequence[str],
    languages: Sequence[str],
    groups: Sequence[Tuple[int, str, str, str]],
    events: Sequence[Tuple[int, str, str, str, str]],
    top_groups: int = 5,
    top_events: int = 5,
) -> dict[str, Any]:
    """
    groups: tuples (id, name, description, combined_text_for_scoring)
    events: tuples (id, title, start_time_iso, location, combined_text_for_scoring)

    Returns JSON-serializable dict with ranked lists and scores in [0, 1] approximately.
    """
    user_raw = _build_user_profile_text(bio, interests, languages)
    user_tokens = _tokenize(user_raw)
    if not user_tokens:
        return {
            "model": "tfidf_cosine_similarity_v1",
            "groups": [],
            "events": [],
            "profile_tokens": 0,
            "message": "No usable words in profile (add a longer bio or interests).",
        }

    group_texts = [t[3] for t in groups]
    event_texts = [t[4] for t in events]
    item_texts = group_texts + event_texts
    all_docs_tokens = [user_tokens] + [_tokenize(t) for t in item_texts]
    n_docs = len(all_docs_tokens)
    df = _document_frequency(all_docs_tokens)
    user_vec = _tfidf_vector(user_tokens, df, n_docs)

    interest_list = list(interests or [])
    lang_list = list(languages or [])

    group_scores: List[Tuple[float, int, List[str]]] = []
    for i, g in enumerate(groups):
        gid, name, desc, gtext = g
        toks = all_docs_tokens[i + 1]
        if not toks:
            continue
        iv = _tfidf_vector(toks, df, n_docs)
        base = _cosine(user_vec, iv)
        boost = _interest_boost(interest_list, lang_list, gtext)
        score = min(1.0, base + boost)
        why = _overlap_terms(user_vec, iv, 8)
        group_scores.append((score, gid, why))

    group_scores.sort(key=lambda x: -x[0])
    top_g = []
    seen = set()
    for score, gid, why in group_scores:
        if gid in seen:
            continue
        seen.add(gid)
        gmeta = next((g for g in groups if g[0] == gid), None)
        if not gmeta:
            continue
        _, name, desc, _ = gmeta
        top_g.append(
            {
                "id": gid,
                "name": name,
                "description": desc,
                "score": round(score, 4),
                "match_terms": why,
            }
        )
        if len(top_g) >= top_groups:
            break

    offset = len(groups)
    event_scores: List[Tuple[float, int, List[str]]] = []
    for j, ev in enumerate(events):
        eid, title, start_iso, loc, etext = ev
        idx = offset + j + 1
        if idx >= len(all_docs_tokens):
            continue
        toks = all_docs_tokens[idx]
        if not toks:
            continue
        iv = _tfidf_vector(toks, df, n_docs)
        base = _cosine(user_vec, iv)
        boost = _interest_boost(interest_list, lang_list, etext)
        score = min(1.0, base + boost)
        why = _overlap_terms(user_vec, iv, 8)
        event_scores.append((score, eid, why))

    event_scores.sort(key=lambda x: -x[0])
    top_e = []
    seen_e = set()
    for score, eid, why in event_scores:
        if eid in seen_e:
            continue
        seen_e.add(eid)
        em = next((e for e in events if e[0] == eid), None)
        if not em:
            continue
        _, title, start_iso, loc, _ = em
        top_e.append(
            {
                "id": eid,
                "title": title,
                "start_time": start_iso,
                "location": loc,
                "score": round(score, 4),
                "match_terms": why,
            }
        )
        if len(top_e) >= top_events:
            break

    return {
        "model": "tfidf_cosine_similarity_v1",
        "groups": top_g,
        "events": top_e,
        "profile_tokens": len(user_tokens),
        "message": None,
    }
