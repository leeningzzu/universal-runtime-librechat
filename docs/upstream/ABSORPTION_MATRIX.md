# LibreChat upstream absorption matrix

For each new stable LibreChat release, compare only affected capability families.

| Result | Action |
|---|---|
| UPSTREAM_ABSORBED | delete the custom seam |
| UPSTREAM_EQUIVALENT | deprecate the custom seam |
| UPSTREAM_PARTIAL | retain only the smallest governance seam |
| GENUINE_GAP | keep/rebase the thin adapter |
| BREAKING_CHANGE | stop and revalidate only invalidated proof families |
| NO_MATERIAL_CHANGE | no-op |

Compare Projects, Files/File Search/RAG, Memory, Skills, MCP, Agents, Artifacts, Code workspaces, background/scheduled behavior, providers/config migrations, and auth/ACL.

Never auto-upgrade Production merely because a newer upstream release exists.
