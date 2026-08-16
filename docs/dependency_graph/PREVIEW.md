# Previewing the Dependency Graph

This document explains how to preview the generated dependency graphs in different formats.

## 1. Mermaid Format (Recommended for GitHub)

The Mermaid format can be viewed directly in GitHub or using online Mermaid editors.

### Option A: View in GitHub

1. Open `docs/dependency_graph/dependencies.mmd` in GitHub
1. GitHub will automatically render Mermaid diagrams

### Option B: Online Mermaid Editor

1. Copy the contents of `dependencies.mmd`
1. Paste into one of these online editors:
   - https://mermaid.live/
   - https://mermaid-js.github.io/mermaid-live-editor/

### Option C: View in VS Code

If you have the Mermaid extension installed in VS Code, it will preview automatically.

## 2. DOT Format (Graphviz)

### Option A: Convert to Image (if Graphviz is installed)

```bash
# Generate PNG
dot -Tpng docs/dependency_graph/dependencies.dot -o docs/dependency_graph/dependencies.png

# Generate SVG (scalable)
dot -Tsvg docs/dependency_graph/dependencies.dot -o docs/dependency_graph/dependencies.svg

# Generate PDF
dot -Tpdf docs/dependency_graph/dependencies.dot -o docs/dependency_graph/dependencies.pdf
```

### Option B: Online Graphviz Editors

1. Copy the contents of `dependencies.dot`
1. Paste into one of these online tools:
   - https://dreampuf.github.io/GraphvizOnline/
   - https://edotor.net/
   - https://graphviz.christine.website/

## 3. JSON Format

### Option A: Pretty Print in Terminal

```bash
cat docs/dependency_graph/dependencies.json | python3 -m json.tool | less
```

### Option B: View in Browser

```bash
# Open in default browser (if you have a JSON viewer extension)
xdg-open docs/dependency_graph/dependencies.json  # Linux
open docs/dependency_graph/dependencies.json      # macOS
```

### Option C: Use jq (if installed)

```bash
jq '.' docs/dependency_graph/dependencies.json | less
```

## 4. Markdown Summary

Simply view the file:

```bash
cat docs/dependency_graph/dependencies.md
# or
less docs/dependency_graph/dependencies.md
```

Or open in any Markdown viewer/editor.

## Quick Preview Commands

Here are some quick commands to preview each format:

```bash
# View Mermaid (copy to online editor)
cat docs/dependency_graph/dependencies.mmd

# View Markdown summary
cat docs/dependency_graph/dependencies.md

# View JSON (pretty printed)
python3 -m json.tool docs/dependency_graph/dependencies.json | less

# Generate PNG from DOT (if Graphviz installed)
dot -Tpng docs/dependency_graph/dependencies.dot -o /tmp/deps.png && xdg-open /tmp/deps.png
```
