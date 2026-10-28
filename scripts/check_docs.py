"""Check local documentation links/images without contacting external services."""
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    errors = []
    checked = 0
    files = [ROOT/'README.md', ROOT/'CONTRIBUTING.md', ROOT/'SECURITY.md', *sorted((ROOT/'docs').rglob('*.md'))]
    for source in files:
        if not source.exists():
            errors.append(f'{source.relative_to(ROOT)}: missing document')
            continue
        text = source.read_text(encoding='utf-8')
        targets = re.findall(r'!?\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)', text)
        targets += re.findall(r'<(?:img|a)\b[^>]*\b(?:src|href)="([^"]+)"', text)
        for target in targets:
            target = unquote(target.strip('<>')).split('#')[0]
            if not target or re.match(r'^[a-z]+:', target):
                continue
            checked += 1
            if not (source.parent/target).exists():
                errors.append(f'{source.relative_to(ROOT)}: missing link {target}')
        for image in re.findall(r'<img\b[^>]*>', text):
            if not re.search(r'\balt="[^"]+"', image):
                errors.append(f'{source.relative_to(ROOT)}: image needs descriptive alt text')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'{len(files)} documents; {checked} local links/images resolve; HTML images have alt text.')
    print('Static checks only: GitHub rendering, Mermaid layout and external URLs require separate verification.')


if __name__ == '__main__':
    main()
