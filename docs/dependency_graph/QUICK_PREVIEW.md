# Quick Preview Guide

## 🎯 Fastest Ways to Preview

### 1. **Markdown Summary** (Text-based, instant)

```bash
cat docs/dependency_graph/dependencies.md
```

Shows a clean list of all dependencies with version specs.

### 2. **Mermaid Diagram** (Visual, works in GitHub)

```bash
# Copy the file content and paste into:
# https://mermaid.live/
cat docs/dependency_graph/dependencies.mmd
```

### 3. **PNG Image** (Visual, already generated)

```bash
# View the generated PNG
xdg-open docs/dependency_graph/dependencies.png  # Linux
open docs/dependency_graph/dependencies.png      # macOS
```

### 4. **SVG Image** (Scalable, already generated)

```bash
# View the generated SVG
xdg-open docs/dependency_graph/dependencies.svg  # Linux
open docs/dependency_graph/dependencies.svg      # macOS
```

### 5. **DOT Graph** (Online visualization)

```bash
# Copy content and paste into:
# https://dreampuf.github.io/GraphvizOnline/
cat docs/dependency_graph/dependencies.dot
```

## 📊 Current Graph Stats

- **Project**: libp2p v0.4.0
- **Runtime dependencies**: 20
- **Optional dependencies**: 32
- **Total nodes**: 44
- **Total edges**: 52

## 🔄 Regenerate Images

If you modify the dependencies and want to regenerate the images:

```bash
# Regenerate all formats
python3 scripts/oso/generate_dependency_graph.py

# Regenerate PNG
dot -Tpng docs/dependency_graph/dependencies.dot -o docs/dependency_graph/dependencies.png

# Regenerate SVG
dot -Tsvg docs/dependency_graph/dependencies.dot -o docs/dependency_graph/dependencies.svg
```
