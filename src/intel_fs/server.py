from __future__ import annotations

from pathlib import Path
from fastmcp import FastMCP
import os
import ast

# 1️⃣ Create the MCP server FIRST
mcp = FastMCP("intel-fs")

# 2️⃣ Define sandbox base directory
#BASE_DIR = Path.cwd().resolve()
BASE_DIR = Path(os.environ.get("MCP_BASE_DIR", Path.cwd())).resolve()

# 3️⃣ Define tools AFTER mcp exists
@mcp.tool
def ping() -> dict:
    """Test tool to verify Claude Desktop can call our MCP server."""
    return {"ok": True, "message": "pong"}

@mcp.tool
def list_files(root: str = ".", max_results: int = 200) -> dict:
    """
    List files under a folder inside the sandbox (BASE_DIR).
    Prevents path traversal outside BASE_DIR.
    """
    try:
        if root.startswith("~") or root.startswith("/"):
            return {
                "ok": False,
                "error": "InvalidPath",
                "message": "Use a relative path like '.' or 'src'.",
            }

        root_path = (BASE_DIR / root).resolve()

        # Prevent escaping BASE_DIR
        if BASE_DIR != root_path and BASE_DIR not in root_path.parents:
            return {
                "ok": False,
                "error": "SecurityError",
                "message": "Path escapes the sandbox base directory.",
            }

        if not root_path.exists() or not root_path.is_dir():
            return {
                "ok": False,
                "error": "NotFound",
                "message": f"Folder not found: {root}",
            }

        files = []
        for p in root_path.rglob("*"):
            if p.is_file():
                files.append(str(p.relative_to(BASE_DIR)))
                if len(files) >= max_results:
                    break

        return {
            "ok": True,
            "base_dir": str(BASE_DIR),
            "root": root,
            "count": len(files),
            "files": files,
        }

    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "message": str(e)}


@mcp.tool
def read_file(path: str, max_chars: int = 20000) -> dict:
    """
    Read a text file inside the sandbox (BASE_DIR).
    Safety:
    - only relative paths
    - prevents ../ escaping
    - caps returned content size
    """
    try:
        if path.startswith("~") or path.startswith("/"):
            return {
                "ok": False,
                "error": "InvalidPath",
                "message": "Use a relative path like 'README.md' or 'src/intel_fs/server.py'.",
            }

        fp = (BASE_DIR / path).resolve()

        # Prevent escaping BASE_DIR
        if BASE_DIR != fp and BASE_DIR not in fp.parents:
            return {
                "ok": False,
                "error": "SecurityError",
                "message": "Path escapes the sandbox base directory.",
            }

        if not fp.exists() or not fp.is_file():
            return {
                "ok": False,
                "error": "NotFound",
                "message": f"File not found: {path}",
            }

        text = fp.read_text(encoding="utf-8", errors="ignore")
        truncated = len(text) > max_chars

        return {
            "ok": True,
            "path": str(fp.relative_to(BASE_DIR)),
            "truncated": truncated,
            "content": text[:max_chars],
        }

    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "message": str(e)}


def _summarize_python_ast(text: str) -> dict:
    """Extract lightweight structure from Python code using AST."""
    out = {"functions": [], "classes": [], "imports": [], "error": None}
    try:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out["functions"].append(node.name)
            elif isinstance(node, ast.ClassDef):
                out["classes"].append(node.name)
            elif isinstance(node, ast.Import):
                for n in node.names:
                    out["imports"].append(n.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for n in node.names:
                    out["imports"].append(f"{mod}.{n.name}" if mod else n.name)

        # keep outputs bounded
        out["functions"] = out["functions"][:60]
        out["classes"] = out["classes"][:40]
        out["imports"] = out["imports"][:80]
        return out
    except Exception as e:
        out["error"] = str(e)
        return out

@mcp.tool
def explain_repository(root: str = ".", max_files: int = 60, max_chars_per_file: int = 12000) -> dict:
    """
    Create a Copilot-style structured overview of a Python repository.
    The LLM uses this output to explain what the repo does, main modules, and flow.
    """
    try:
        if root.startswith("~") or root.startswith("/"):
            return {"ok": False, "error": "InvalidPath", "message": "Use a relative path like '.' or 'src'."}

        root_path = (BASE_DIR / root).resolve()
        if BASE_DIR != root_path and BASE_DIR not in root_path.parents:
            return {"ok": False, "error": "SecurityError", "message": "Root escapes the sandbox base directory."}
        if not root_path.exists() or not root_path.is_dir():
            return {"ok": False, "error": "NotFound", "message": f"Folder not found: {root}"}

        py_files = sorted([p for p in root_path.rglob("*.py") if p.is_file()])[:max_files]

        summaries = []
        entry_candidates = []

        for fp in py_files:
            rel = str(fp.relative_to(BASE_DIR))

            # common entrypoints
            low = rel.lower()
            if low.endswith(("main.py", "__main__.py")) or low in ("app.py", "server.py"):
                entry_candidates.append(rel)

            text = fp.read_text(encoding="utf-8", errors="ignore")[:max_chars_per_file]
            summaries.append({
                "path": rel,
                "structure": _summarize_python_ast(text),
                "preview": "\n".join(text.splitlines()[:30])
            })

        # also include a small tree (top-level only)
        top_level = []
        for p in root_path.iterdir():
            top_level.append({"name": p.name, "type": "dir" if p.is_dir() else "file"})
        top_level = sorted(top_level, key=lambda x: (x["type"], x["name"]))

        return {
            "ok": True,
            "base_dir": str(BASE_DIR),
            "root": root,
            "python_files_scanned": len(py_files),
            "entry_point_candidates": entry_candidates[:10],
            "top_level": top_level[:200],
            "file_summaries": summaries
        }

    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "message": str(e)}
    

def _safe_resolve(rel_path: str) -> Path:
    """Resolve a relative path under BASE_DIR with sandbox protection."""
    if rel_path.startswith("~") or rel_path.startswith("/"):
        raise ValueError("InvalidPath: use a relative path.")
    p = (BASE_DIR / rel_path).resolve()
    if p != BASE_DIR and BASE_DIR not in p.parents:
        raise PermissionError("SecurityError: path escapes sandbox.")
    return p

@mcp.tool
def smart_search(
    query: str,
    root: str = ".",
    use_regex: bool = False,
    case_sensitive: bool = False,
    max_hits: int = 50,
    max_file_size_kb: int = 512,
) -> dict:
    """
    Search across text files in the sandbox.
    - Uses ripgrep (rg) if available (fast)
    - Falls back to a Python scan if rg isn't installed
    Returns: path, line number, and matching line snippet.
    """
    try:
        root_path = _safe_resolve(root)
        if not root_path.exists() or not root_path.is_dir():
            return {"ok": False, "error": "NotFound", "message": f"Folder not found: {root}"}

        # Prefer ripgrep if installed
        rg_path = shutil.which("rg")
        if rg_path:
            rg_args = [rg_path, "--line-number", "--no-heading"]
            if not case_sensitive:
                rg_args.append("-i")
            if not use_regex:
                rg_args.append("--fixed-string")

            # Don't search huge binaries; keep it friendly
            rg_args += ["--max-filesize", f"{max_file_size_kb}K"]

            rg_args += [query, "."]

            proc = subprocess.run(
                rg_args,
                cwd=str(root_path),
                capture_output=True,
                text=True,
            )

            hits = []
            for line in proc.stdout.splitlines():
                parts = line.split(":", 2)  # file:line:text
                if len(parts) == 3:
                    pth, ln, txt = parts
                    hits.append(
                        {
                            "path": str((Path(root) / pth).as_posix()),
                            "line": int(ln),
                            "text": txt.strip(),
                        }
                    )
                    if len(hits) >= max_hits:
                        break

            return {
                "ok": True,
                "engine": "ripgrep",
                "query": query,
                "root": root,
                "hits": hits,
                "truncated": len(hits) >= max_hits,
            }

        # Python fallback
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(query if use_regex else re.escape(query), flags=flags)

        hits = []
        # Scan common text-like files; you can expand later
        exts = {".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".env", ".ini", ".cfg"}

        for fp in root_path.rglob("*"):
            if not fp.is_file():
                continue
            if fp.suffix.lower() not in exts:
                continue
            # Skip very large files
            try:
                if fp.stat().st_size > max_file_size_kb * 1024:
                    continue
            except Exception:
                continue

            try:
                with fp.open("r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, start=1):
                        if pattern.search(line):
                            hits.append(
                                {
                                    "path": str(fp.relative_to(BASE_DIR).as_posix()),
                                    "line": i,
                                    "text": line.strip(),
                                }
                            )
                            if len(hits) >= max_hits:
                                return {
                                    "ok": True,
                                    "engine": "python",
                                    "query": query,
                                    "root": root,
                                    "hits": hits,
                                    "truncated": True,
                                }
            except Exception:
                continue

        return {
            "ok": True,
            "engine": "python",
            "query": query,
            "root": root,
            "hits": hits,
            "truncated": False,
        }

    except ValueError as e:
        return {"ok": False, "error": "InvalidPath", "message": str(e)}
    except PermissionError as e:
        return {"ok": False, "error": "SecurityError", "message": str(e)}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "message": str(e)}



# 4️⃣ Run server
if __name__ == "__main__":
    mcp.run()
