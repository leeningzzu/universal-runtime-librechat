# LibreChat custom seam inventory

This source repository publishes a reviewed private-build seam inventory plus narrowly scoped exact upstream-relative patches when provenance, license, current-consumer proof, and regression evidence are complete. It remains **not** a raw LibreChat fork or compiled shell. The full upstream v0.8.8 tag SHA is recorded in `docs/upstream/librechat.lock.json`, and LibreChat attribution remains in `NOTICE`.

## Published exact patch

- `chatanywhere-native-model-catalog-r002.patch` — preserves LibreChat's native `user_provided` credential and selector ownership while adding a bounded ChatAnywhere catalogue timeout and credential-fingerprinted positive cache.
- `chatanywhere-native-model-catalog-r002.manifest.json` — binds exact source and compiled parent/candidate SHAs plus isolated/current-consumer proof ceilings.
- `tests/test_chatanywhere_model_catalog_patch_contract.py` — fails if the patch, manifest, provider scope, or promoted strategy linkage drifts.

The patch does not contain user credentials, model responses, private Project data, Mongo data, or a Docker image.

Known current private-build modified/added files observed during the absorption audit:

- api/app/clients/tools/util/projectChatRecall.js — sha256 5c2c8f559aef26ef01e1987bafbd6a38b215bebd3705a3d405192d82a3f51eab
- api/app/clients/tools/util/handleTools.js — sha256 8b0ad11b930848e94eeea33b90aa4c63d5f0e6b8f64b08515958aa832355967e
- api/server/services/ToolService.js — sha256 0c1f764b8f44a4087f051dd3f31cb4e2837079483724448a206ae4e5630e5ff4
- api/server/routes/runtimeProjects.js — sha256 82760fbc15b95b58c3ce315d9efe5dda48cf2f5b1f4bde6522dafabd96330644
- api/server/routes/projects.js — sha256 6ca05c2e04e2d2882f61d1937b59a23ff5c7141cb5e69531655605240e96ee76
- api/server/services/ProjectAssistantProfile.js — sha256 d254effe34a80f9d67f87250f88bbccb343fe16f1af4af69f4518cfb686635f3
- api/server/controllers/agents/client.js — sha256 06cb2bb2cdf4c6934f3407a82d1b0f25888fd983bffebb2ffdf265ba67381c11
- api/server/routes/agents/chat.js — sha256 394acd52bfaab12ae266fc160789150141e2a3ce78d70d16c8641c05c359e295
- client/src/components/Projects/ProjectWorkspace.tsx — sha256 3771f74e3060e3933c2e81b977d52966a17944e6d7038e7d9326622f86dd6b37
- client/src/components/Projects/ProjectCreateDialog.tsx — sha256 c32a9fe87d64881bd2a0ca17f1e20e598973dfbe9b6ee469e74de8d914fe9304
- client/src/components/Projects/ProjectEditDialog.tsx — sha256 66c1ef2554cd1a1ba5220ed0480b4b7659fe5947f38a8fa89a25db391f340bfc
- client/src/components/Projects/ProjectDeleteDialog.tsx — sha256 51f7b1c8bb6e67e3ce0c467cd08fe167b35836b2ce491e5aa9c25d5983b00ff0
- client/src/components/Projects/RuntimeProjectWorkspace.tsx — sha256 0bd1004b54ccffcbc52c6563453a6c237d1c2106726209fd2c99d8961b23390a
- client/src/utils/__tests__/getDefaultModelSpec.test.ts — sha256 0584e818f2dd96455447ab4ce367a68fc8cda11c296285edf1f0feb60a3e17df

Before patch publication, regenerate this list from an exact upstream diff rather than treating this observed list as exhaustive.
