"""Apply the media export upgrade to the existing, separately installed collector."""
import argparse
from pathlib import Path


def replace_once(path, old, new):
    content = path.read_text()
    if new in content:
        return
    if old not in content:
        raise SystemExit(f"Collector layout changed: {path.name}")
    path.with_suffix(path.suffix + ".before-crm-media").write_text(content)
    path.write_text(content.replace(old, new, 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    src = args.root / "src/linkedin_enrichment"
    replace_once(src / "models.py",
                 "    mutual_count: int | None = None",
                 "    avatar_url: str | None = None\n    mutual_count: int | None = None")
    replace_once(src / "voyager.py",
                 "from .models import ExtendedEducation, ExtendedPerson",
                 "from .models import ExtendedEducation, ExtendedPerson\nfrom .profile_media import profile_avatar")
    replace_once(src / "voyager.py",
                 "    return enrich_voyager_educations(parsed, raw)",
                 '    parsed["avatar_url"] = profile_avatar(raw, public_identifier)\n    return enrich_voyager_educations(parsed, raw)')
    replace_once(src / "voyager.py", '        name=data.get("full_name"),',
                 '        name=data.get("full_name"),\n        avatar_url=data.get("avatar_url"),')
    replace_once(src / "storage.py", '        "about": data.get("about"),',
                 '        "about": data.get("about"),\n        "avatar_url": data.get("avatar_url"),')
    script = args.root / "scripts/sync-host.sh"
    replace_once(script, 'chmod 600 "$PAYLOAD"',
                 'chmod 600 "$PAYLOAD"\n# Deliver media URLs to the NAS even while provider collection is paused.\n"$ROOT/scripts/publish-crm.sh" "$PAYLOAD"')


if __name__ == "__main__":
    main()
