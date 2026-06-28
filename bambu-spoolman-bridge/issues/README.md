# Issues (Backlog als Markdown)

Jede Datei = ein vorbereitetes GitHub-Issue. Im **neuen Repo** als echte Issues importieren
(GitHub-Issues sind im aktuellen Fork deaktiviert). IDs:
- `BR-xx` = Bug/Fix/Chore aus dem Code-/Architektur-Review (siehe `../docs/review-findings-backlog.md`).
- `F-xx` = Feature/Task.

Header je Datei: `Type · Severity · Area · Status · Refs`. Templates: `../.github/ISSUE_TEMPLATE/`.

## Import (im neuen Repo, mit GitHub CLI)
```bash
for f in issues/BR-*.md issues/F-*.md; do
  title=$(sed -n 's/^# //p' "$f" | head -1)
  labels=$(sed -n 's/.*\*\*Type:\*\* \([a-z]*\).*/\1/p' "$f" | head -1)
  gh issue create --title "$title" --body-file "$f" --label "${labels:-task}"
done
```
Severity-Mapping (optional): 🔴=`priority:critical`, 🟠=`priority:high`, 🟡=`priority:low`.
