"""
BrainrotWorkflow - Reddit Story Scraper
Scarica i top post giornalieri da r/AITA e r/relationship_advice.

Funziona senza registrazione. Se ricevi errori 403, aggiungi le credenziali
dell'app Reddit in config.json (vedi istruzioni in fondo al file).
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).parent
CONFIG_PATH = BASE / "config.json"

# User-Agent che simula Firefox — funziona senza autenticazione
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
        "Gecko/20100101 Firefox/125.0"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}

MARKDOWN_RE = re.compile(
    r"(\*{1,3}|_{1,3}|~~|`{1,3}|&amp;|&lt;|&gt;|&nbsp;|#+ |\[|\]|\(http[^\)]+\))"
)


def carica_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def pulisci_testo(testo: str) -> str:
    testo = MARKDOWN_RE.sub(" ", testo)
    testo = re.sub(r"http\S+", "", testo)
    testo = re.sub(r"\s{2,}", " ", testo).strip()
    return testo


def conta_parole(testo: str) -> int:
    return len(testo.split())


def slug(titolo: str) -> str:
    s = re.sub(r"[^\w\s-]", "", titolo[:60]).strip()
    return re.sub(r"\s+", "_", s) or "reddit_post"


def fetch_posts_public(subreddit: str, limit: int, time_filter: str) -> list[dict]:
    """Fetch senza autenticazione via API pubblica Reddit."""
    url = f"https://www.reddit.com/r/{subreddit}/top.json"
    params = {"t": time_filter, "limit": limit, "raw_json": 1}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()["data"]["children"]


def fetch_posts_praw(subreddit: str, limit: int, time_filter: str, reddit_cfg: dict) -> list:
    """Fetch con PRAW (richiede client_id e client_secret in config.json)."""
    import praw
    reddit = praw.Reddit(
        client_id=reddit_cfg["client_id"],
        client_secret=reddit_cfg["client_secret"],
        user_agent="BrainrotWorkflow/1.0 (script; educational content pipeline)",
    )
    reddit.read_only = True
    return list(reddit.subreddit(subreddit).top(time_filter=time_filter, limit=limit))


def processa_raw(post_data: dict, reddit_cfg: dict, time_filter: str) -> dict | None:
    """Elabora un post dal formato JSON grezzo (API pubblica)."""
    if post_data.get("stickied") or post_data.get("removed_by_category"):
        return None
    if post_data.get("score", 0) < reddit_cfg["min_score"]:
        return None

    testo_raw = (post_data.get("selftext") or "").strip()
    if not testo_raw or testo_raw in ("[removed]", "[deleted]"):
        return None

    testo = pulisci_testo(testo_raw)
    n_parole = conta_parole(testo)
    if n_parole < reddit_cfg["min_parole"]:
        return None
    if n_parole > reddit_cfg["max_parole"]:
        testo = " ".join(testo.split()[: reddit_cfg["max_parole"]])

    titolo_raw = post_data.get("title", "Senza titolo")
    sub_name = post_data.get("subreddit", "unknown")
    score = post_data.get("score", 0)
    post_id = post_data.get("id", "")

    hook = f"Okay so I posted this on Reddit and it blew up. Title: {titolo_raw}. "
    return {
        "sorgente": f"reddit/r/{sub_name}/{post_id}",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "selezionata": True,
        "motivo": f"Top post r/{sub_name} ({time_filter}) - score {score:,}",
        "titolo": slug(titolo_raw),
        "score_engagement": min(10, max(1, round(score / 1000))),
        "reddit_score": score,
        "subreddit": sub_name,
        "post_id": post_id,
        "testo_ottimizzato": hook + testo,
    }


def processa_praw(submission, reddit_cfg: dict, time_filter: str) -> dict | None:
    """Elabora un submission PRAW."""
    if submission.stickied or submission.removed_by_category:
        return None
    if submission.score < reddit_cfg["min_score"]:
        return None

    testo_raw = (submission.selftext or "").strip()
    if not testo_raw or testo_raw in ("[removed]", "[deleted]"):
        return None

    testo = pulisci_testo(testo_raw)
    n_parole = conta_parole(testo)
    if n_parole < reddit_cfg["min_parole"]:
        return None
    if n_parole > reddit_cfg["max_parole"]:
        testo = " ".join(testo.split()[: reddit_cfg["max_parole"]])

    titolo_raw = submission.title or "Senza titolo"
    sub_name = submission.subreddit.display_name
    score = submission.score
    post_id = submission.id

    hook = f"Okay so I posted this on Reddit and it blew up. Title: {titolo_raw}. "
    return {
        "sorgente": f"reddit/r/{sub_name}/{post_id}",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "selezionata": True,
        "motivo": f"Top post r/{sub_name} ({time_filter}) - score {score:,}",
        "titolo": slug(titolo_raw),
        "score_engagement": min(10, max(1, round(score / 1000))),
        "reddit_score": score,
        "subreddit": sub_name,
        "post_id": post_id,
        "testo_ottimizzato": hook + testo,
    }


def salva_storia(storia: dict) -> Path:
    output_dir = BASE / carica_config()["paths"]["story_inbox"]
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{storia['titolo']}.json"
    counter = 1
    while path.exists():
        path = OUT_DIR / f"{storia['titolo']}_{counter}.json"
        counter += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(storia, f, ensure_ascii=False, indent=2)
    return path


def main(dry_run: bool = False) -> None:
    cfg = carica_config()
    reddit_cfg = cfg.get("reddit", {})

    subreddits = reddit_cfg.get("subreddits", ["AITA", "relationship_advice"])
    limit = reddit_cfg.get("post_limit", 10)
    time_filter = reddit_cfg.get("time_filter", "day")
    use_praw = bool(reddit_cfg.get("client_id") and reddit_cfg.get("client_secret"))

    print(f"\n=== Reddit Scraper - top/{time_filter} ===")
    print(f"Modalita: {'PRAW (autenticato)' if use_praw else 'API pubblica (anonima)'}")
    print(f"Subreddits: {subreddits}  |  Limit per sub: {limit}")
    print(f"Filtri: min_score={reddit_cfg['min_score']}, "
          f"parole {reddit_cfg['min_parole']}-{reddit_cfg['max_parole']}\n")

    totale_salvate = 0

    for sub_name in subreddits:
        print(f"--- r/{sub_name} ---")
        salvate = 0

        try:
            if use_praw:
                submissions = fetch_posts_praw(sub_name, limit, time_filter, reddit_cfg)
                for submission in submissions:
                    storia = processa_praw(submission, reddit_cfg, time_filter)
                    if storia is None:
                        continue
                    n_parole = conta_parole(storia["testo_ottimizzato"])
                    label = f"[score {storia['reddit_score']:,} | {n_parole} parole] {storia['titolo'][:50]}"
                    if dry_run:
                        print(f"  [DRY RUN] {label}")
                    else:
                        path = salva_storia(storia)
                        print(f"  Salvata: {path.name} - {label}")
                    salvate += 1
            else:
                children = fetch_posts_public(sub_name, limit, time_filter)
                for child in children:
                    storia = processa_raw(child["data"], reddit_cfg, time_filter)
                    if storia is None:
                        continue
                    n_parole = conta_parole(storia["testo_ottimizzato"])
                    label = f"[score {storia['reddit_score']:,} | {n_parole} parole] {storia['titolo'][:50]}"
                    if dry_run:
                        print(f"  [DRY RUN] {label}")
                    else:
                        path = salva_storia(storia)
                        print(f"  Salvata: {path.name} - {label}")
                    salvate += 1

        except Exception as e:
            print(f"  [ERRORE] r/{sub_name}: {e}")
            if "403" in str(e) and not use_praw:
                print("  Suggerimento: Reddit ha bloccato la richiesta anonima.")
                print("  Crea un'app su reddit.com/prefs/apps e aggiungi le credenziali in config.json.")

        print(f"  Totale r/{sub_name}: {salvate} storie salvate\n")
        totale_salvate += salvate

        if sub_name != subreddits[-1]:
            time.sleep(2)

    print(f"=== Completato: {totale_salvate} storie totali ===")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
