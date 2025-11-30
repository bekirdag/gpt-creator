import json
import re
import sys
from pathlib import Path

STOPWORDS = {
    "the",
    "and",
    "with",
    "from",
    "base",
    "template",
    "project",
    "app",
    "service",
    "system",
}


def tokenize(text: str):
    for token in re.split(r"[^a-z0-9]+", text.lower()):
        if len(token) >= 3:
            yield token


def gather_template_tokens(path: Path):
    tokens = set(tokenize(path.name))

    tags_file = path / "tags.txt"
    if tags_file.exists():
        for line in tags_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            tokens.update(tokenize(line))

    template_json = path / "template.json"
    if template_json.exists():
        try:
            data = json.loads(template_json.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            data = {}
        for field in ("tags", "keywords", "stack"):
            value = data.get(field)
            if isinstance(value, str):
                tokens.update(tokenize(value))
            elif isinstance(value, list):
                for entry in value:
                    tokens.update(tokenize(str(entry)))

    return {token for token in tokens if token not in STOPWORDS}


def choose_template(rfp_text: str, template_paths):
    scores = []
    for template in template_paths:
        path = Path(template)
        tokens = gather_template_tokens(path)
        score = 0
        for token in tokens:
            if token and token in rfp_text:
                score += rfp_text.count(token)
        scores.append((score, template))
    scores.sort(reverse=True)
    if scores and scores[0][0] > 0:
        return scores[0][1]
    return ""


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    rfp_path = Path(sys.argv[1])
    if not rfp_path.exists():
        return 1
    templates = sys.argv[2:]
    rfp_text = rfp_path.read_text(encoding="utf-8", errors="ignore").lower()
    chosen = choose_template(rfp_text, templates)
    if chosen:
        print(chosen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
