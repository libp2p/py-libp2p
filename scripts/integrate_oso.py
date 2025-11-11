#!/usr/bin/env python3
"""
Integration script for Open Source Observer (OSO) API.

This script helps upload and query dependency graph data using OSO's GraphQL API
or the pyoso Python library.

Requirements:
    - OSO API key (get from https://www.opensource.observer/account/settings)
    - Optional: pip install pyoso requests
"""

import json
import os
from pathlib import Path
import sys
from typing import Any

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)


# OSO API Configuration
OSO_API_URL = "https://api.opensource.observer/graphql"
OSO_DOCS_URL = "https://docs.opensource.observer/docs/get-started/api/"


def load_api_key() -> str | None:
    """Load OSO API key from environment variable or file."""
    # Try environment variable first
    api_key = os.getenv("OSO_API_KEY")
    if api_key:
        return api_key

    # Try .env file
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.startswith("OSO_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    # Try config file
    config_file = Path(__file__).parent.parent / ".oso_config"
    if config_file.exists():
        with open(config_file) as f:
            return f.read().strip()

    return None


def query_oso_graphql(query: str, api_key: str, variables: dict | None = None) -> dict:
    """
    Query OSO's GraphQL API.

    Args:
        query: GraphQL query string
        api_key: OSO API key for authentication
        variables: Optional GraphQL variables

    Returns:
        JSON response from API

    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    try:
        response = requests.post(OSO_API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error querying OSO API: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response: {e.response.text}")
        raise


def load_dependency_graph(graph_file: Path) -> dict[str, Any]:
    """Load dependency graph JSON file."""
    with open(graph_file) as f:
        return json.load(f)


def format_dependency_graph_for_oso(graph_data: dict[str, Any]) -> dict[str, Any]:
    """
    Format dependency graph data for OSO API.

    This converts our internal format to a format that OSO might expect.
    Adjust based on OSO's actual API requirements.
    """
    return {
        "project": graph_data.get("project", {}),
        "dependencies": [
            {
                "name": node["id"],
                "type": node.get("type", "dependency"),
                "version": node.get("version", node.get("version_spec", "")),
            }
            for node in graph_data.get("nodes", [])
            if node.get("id") != graph_data.get("project", {}).get("name", "libp2p")
        ],
        "edges": graph_data.get("edges", []),
    }


def query_project_metrics(project_name: str, api_key: str) -> dict:
    """
    Query OSO for project metrics.

    Example GraphQL query to get project information.
    Adjust based on OSO's actual GraphQL schema.
    """
    query = """
    query GetProject($projectName: String!) {
      project(name: $projectName) {
        name
        description
        stars
        forks
        contributors
        dependencies {
          name
          version
        }
      }
    }
    """

    variables = {"projectName": project_name}
    return query_oso_graphql(query, api_key, variables)


def upload_dependency_graph(graph_data: dict[str, Any], api_key: str) -> dict:
    """
    Upload dependency graph to OSO.

    Note: This is a placeholder. OSO's actual API may require different
    endpoints or data formats. Check OSO documentation for the correct method.
    """
    # Format data for OSO
    formatted_data = format_dependency_graph_for_oso(graph_data)

    # Example mutation (adjust based on OSO's actual schema)
    mutation = """
    mutation UploadDependencyGraph($data: DependencyGraphInput!) {
      uploadDependencyGraph(data: $data) {
        success
        message
      }
    }
    """

    variables = {"data": formatted_data}
    return query_oso_graphql(mutation, api_key, variables)


def main():
    """Main function for OSO integration."""
    repo_root = Path(__file__).parent.parent
    graph_file = repo_root / "docs" / "dependency_graph" / "dependencies.json"

    print("🔗 OSO Integration Script")
    print("=" * 50)
    print()

    # Check for API key
    api_key = load_api_key()
    if not api_key:
        print("❌ OSO API key not found!")
        print()
        print("To get an API key:")
        print("1. Visit https://www.opensource.observer/")
        print("2. Create an account or log in")
        print("3. Go to Account Settings")
        print("4. Generate a new API key")
        print()
        print("Then set it in one of these ways:")
        print("  - Environment variable: export OSO_API_KEY='your-key'")
        print("  - .env file: echo 'OSO_API_KEY=your-key' >> .env")
        print("  - Config file: echo 'your-key' > .oso_config")
        print()
        print(f"📚 API Documentation: {OSO_DOCS_URL}")
        sys.exit(1)

    print("✅ API key found")
    print()

    # Load dependency graph
    if not graph_file.exists():
        print(f"❌ Dependency graph file not found: {graph_file}")
        print("   Run: python3 scripts/generate_dependency_graph.py")
        sys.exit(1)

    print(f"📦 Loading dependency graph from {graph_file.name}...")
    graph_data = load_dependency_graph(graph_file)
    print(f"   Project: {graph_data.get('project', {}).get('name', 'unknown')}")
    print(f"   Nodes: {len(graph_data.get('nodes', []))}")
    print(f"   Edges: {len(graph_data.get('edges', []))}")
    print()

    # Example: Query project metrics
    project_name = graph_data.get("project", {}).get("name", "libp2p")
    print(f"🔍 Querying OSO for project: {project_name}")
    print("   (This is an example - adjust based on OSO's actual API)")
    print()

    try:
        # Note: This query may need adjustment based on OSO's actual GraphQL schema
        result = query_project_metrics(project_name, api_key)
        print("✅ Query successful!")
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"⚠️  Query failed: {e}")
        print()
        print("This might be because:")
        print("1. The GraphQL schema is different - check OSO documentation")
        print("2. The project name format is different")
        print("3. The API endpoint or authentication method has changed")
        print()
        print(f"📚 Check the API documentation: {OSO_DOCS_URL}")

    print()
    print("💡 Next Steps:")
    print("1. Review OSO's GraphQL API documentation")
    print("2. Adjust queries based on OSO's actual schema")
    print("3. Use pyoso library for Python-based queries:")
    print("   pip install pyoso")
    print('   python3 -c "import pyoso; ..."')
    print()
    print("📚 Resources:")
    print(f"   - API Docs: {OSO_DOCS_URL}")
    print("   - Python Library: https://pypi.org/project/pyoso/")
    print("   - Website: https://www.opensource.observer/")


if __name__ == "__main__":
    main()
