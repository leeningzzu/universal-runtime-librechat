const express = require('express');
const { logger } = require('@librechat/data-schemas');
const {
  createMessageFilterPii,
  reportLocatorTraversalFailure,
  generateCheckAccess,
  skipAgentCheck,
  applyResumeContext,
  applyResumeModelParameters,
  GenerationJobManager,
  getSafeErrorMetadata,
} = require('@librechat/api');
const {
  PermissionTypes,
  Permissions,
  PermissionBits,
} = require('librechat-data-provider');
const {
  moderateText,
  // validateModel,
  validateConvoAccess,
  buildEndpointOption,
  canAccessAgentFromBody,
} = require('~/server/middleware');
const { initializeClient } = require('~/server/services/Endpoints/agents');
const guardSubagentThreadTurn = require('~/server/middleware/validate/subagentThreadTurn');
const AgentController = require('~/server/controllers/agents/request');
const ResumeController = require('~/server/controllers/agents/resume');
const addTitle = require('~/server/services/Endpoints/agents/title');
const {
  PROJECT_CONTEXT_POLICY_PROJECT_ONLY,
  buildProjectRuntimeContextBinding,
  projectRuntimeContextBindingEquals,
  fetchProjectRuntimeContext,
  fetchProjectLocalWorkBinding,
  formatProjectRuntimeContext,
  formatProjectLocalWorkContext,
} = require('~/server/services/ProjectAssistantProfile');
const { getFiles, getRoleByName, getChatProject } = require('~/models');

const router = express.Router();

const checkAgentAccess = generateCheckAccess({
  permissionType: PermissionTypes.AGENTS,
  permissions: [Permissions.USE],
  skipCheck: skipAgentCheck,
  getRoleByName,
});
const checkAgentResourceAccess = canAccessAgentFromBody({
  requiredPermission: PermissionBits.VIEW,
});


const buildProjectValidatedLocalWork = (projectId, localWork) => {
  const binding = localWork?.binding;
  if (
    typeof projectId !== 'string' ||
    !projectId ||
    !Number.isInteger(localWork?.projectRevision) ||
    localWork.projectRevision < 1 ||
    binding?.executor !== 'webcodex-local' ||
    binding?.binding_class !== 'MACHINE_LOCAL_PROJECT_ROOT' ||
    typeof binding?.local_project_root !== 'string' ||
    !binding.local_project_root ||
    typeof localWork?.webcodexProjectId !== 'string' ||
    !localWork.webcodexProjectId
  ) {
    return null;
  }
  return Object.freeze({
    librechat_project_id: projectId,
    project_revision: localWork.projectRevision,
    executor: binding.executor,
    binding_class: binding.binding_class,
    local_project_root: binding.local_project_root,
    webcodex_project_id: localWork.webcodexProjectId,
  });
};

const projectLocalWorkPresentationFromValidated = (validated) => ({
  projectRevision: validated.project_revision,
  binding: {
    executor: validated.executor,
    binding_class: validated.binding_class,
    local_project_root: validated.local_project_root,
  },
  webcodexProjectId: validated.webcodex_project_id,
});

const ensureProjectValidatedLocalWork = async (req, projectId) => {
  const current = req._projectValidatedLocalWork;
  if (
    current?.librechat_project_id === projectId &&
    current?.executor === 'webcodex-local' &&
    current?.binding_class === 'MACHINE_LOCAL_PROJECT_ROOT' &&
    Number.isInteger(current?.project_revision) &&
    current.project_revision > 0 &&
    typeof current?.webcodex_project_id === 'string' &&
    current.webcodex_project_id
  ) {
    if (!req._projectLocalWorkPresentation) {
      req._projectLocalWorkPresentation = projectLocalWorkPresentationFromValidated(current);
    }
    return current;
  }
  delete req._projectValidatedLocalWork;
  delete req._projectLocalWorkPresentation;
  const localWork = await fetchProjectLocalWorkBinding(projectId);
  req._projectLocalWorkPresentation = localWork;
  const validated = buildProjectValidatedLocalWork(projectId, localWork);
  if (validated) {
    req._projectValidatedLocalWork = validated;
  }
  return validated;
};


const loadProjectRuntimeContext = async (req, res, next) => {
  const isResume = req.path === '/resume';
  const requestedProjectId =
    typeof req.body?.chatProjectId === 'string' ? req.body.chatProjectId.trim() : '';
  const resolvedProjectId =
    typeof req.resolvedConversation?.chatProjectId === 'string'
      ? req.resolvedConversation.chatProjectId.trim()
      : '';
  const clientBinding = req.body?.projectContextBinding;
  if (!isResume && req.body && Object.prototype.hasOwnProperty.call(req.body, 'projectContextBinding')) {
    delete req.body.projectContextBinding;
  }
  const restoredBinding = isResume ? clientBinding : null;
  const boundProjectId =
    restoredBinding && typeof restoredBinding === 'object' &&
    typeof restoredBinding.librechat_project_id === 'string'
      ? restoredBinding.librechat_project_id.trim()
      : '';
  const projectIds = [...new Set([requestedProjectId, resolvedProjectId, boundProjectId].filter(Boolean))];
  if (projectIds.length > 1) {
    return res.status(409).json({
      error: 'Project context scope changed',
      message: 'Request, conversation and paused Project identities do not match; start a new turn.',
    });
  }
  const projectId = projectIds[0] ?? '';
  if (!projectId) {
    return next();
  }
  if (isResume && (!restoredBinding || typeof restoredBinding !== 'object')) {
    return res.status(409).json({
      error: 'Project context binding unavailable',
      message: 'This paused Project turn predates exact context binding; start a new turn.',
    });
  }
  try {
    const userId = req.user?.id ?? req.user?._id?.toString() ?? '';
    const project = await getChatProject(userId, projectId);
    if (!project) {
      return res.status(404).json({ error: 'Project not found' });
    }
    const context = await fetchProjectRuntimeContext(projectId);
    const currentBinding = buildProjectRuntimeContextBinding(projectId, context);
    if (
      isResume &&
      !projectRuntimeContextBindingEquals(restoredBinding, currentBinding)
    ) {
      return res.status(409).json({
        error: 'Project context changed while paused',
        message: 'Project policy, Instructions, Memory or Sources changed after approval; start a new turn.',
      });
    }
    req.body.chatProjectId = projectId;
    req.body.projectContextBinding = currentBinding;
    req._projectRuntimeContext = context;
    const projectRuntimeContextBlock = formatProjectRuntimeContext(context);
    req._projectRuntimeContextBlock = projectRuntimeContextBlock;
    try {
      await ensureProjectValidatedLocalWork(req, projectId);
      req._projectRuntimeContextBlock = [
        projectRuntimeContextBlock,
        formatProjectLocalWorkContext(req._projectLocalWorkPresentation ?? null),
      ]
        .filter((value) => typeof value === 'string' && value.trim())
        .join('\n\n');
    } catch (error) {
      logger.warn(
        '[agents/chat] Optional Project local-work admission unavailable; keeping local executor tools disabled',
        getSafeErrorMetadata(error),
      );
    }
    if (context.contextPolicy === PROJECT_CONTEXT_POLICY_PROJECT_ONLY) {
      const config = req.config ?? {};
      req.config = {
        ...config,
        memory: {
          ...(config.memory ?? {}),
          disabled: true,
        },
      };
    }
    return next();
  } catch (error) {
    logger.warn('[agents/chat] Project Runtime context load failed', getSafeErrorMetadata(error));
    const status = Number.isInteger(error?.status) ? error.status : 502;
    return res.status(status).json({
      error: 'Project context unavailable',
      message: error?.message || 'Project Runtime context resolution failed',
    });
  }
};


/**
 * Replay the paused turn's graph-determining config onto a resume request BEFORE the
 * rest of the chain (PII filter, agent-access, buildEndpointOption) reads it. The client
 * can't reliably re-send the ephemeral-agent config after a reload/cross-session, so the
 * server restores it from the pending action — the resume then rebuilds the SAME
 * agent/graph the run paused on (and a crafted resume can't swap the tool set). No-op for
 * every non-resume route.
 */
const restoreResumeContext = async (req, res, next) => {
  if (req.path !== '/resume') {
    return next();
  }
  try {
    const streamId = req.body?.conversationId;
    if (streamId) {
      const job = await GenerationJobManager.getJob(streamId);
      const resumeContext = job?.metadata?.pendingAction?.resumeContext;
      applyResumeContext(req.body, resumeContext);
      // Replay the paused turn's resolved model parameters. Ephemeral agents derive these
      // (temperature, max tokens, custom endpoint params) from the request body, which the
      // resume payload omits — without this the continuation runs with defaults. They're
      // scattered top-level fields (folded into model_parameters by buildOptions' rest
      // spread), not part of the RESUME_CONTEXT_KEYS allowlist, so merge them back here.
      // Generation params are authoritative, but routing, graph identity, and resume-action
      // fields remain owned by the restored context/request envelope.
      applyResumeModelParameters(req.body, resumeContext?.model_parameters);
    }
  } catch (err) {
    logger.warn('[agents/chat] Failed to restore resume context', getSafeErrorMetadata(err));
  }
  next();
};

router.use(restoreResumeContext);
router.use(
  createMessageFilterPii({
    onTraversalFailure: reportLocatorTraversalFailure,
    getConfig: (req) => req.config?.messageFilter?.pii,
    getFilters: (req) => req.config?.filters,
    getFiles,
  }),
);
router.use(moderateText);
router.use(checkAgentAccess);
router.use(checkAgentResourceAccess);
router.use(validateConvoAccess);
router.use(guardSubagentThreadTurn);
router.use(loadProjectRuntimeContext);
router.use(buildEndpointOption);

const controller = async (req, res, next) => {
  await AgentController(req, res, next, initializeClient, addTitle);
};

const resumeController = async (req, res, next) => {
  await ResumeController(req, res, next, initializeClient, addTitle);
};

/**
 * @route POST /resume
 * @desc Resume a generation paused for human-in-the-loop review (tool approval or
 *       ask-user answer). Shares this router's middleware so the agent/endpoint are
 *       reconstructed from the request exactly like a normal turn. Declared before
 *       `/:endpoint` so it is not captured as an ephemeral endpoint name.
 * @access Private
 * @returns {void}
 */
router.post('/resume', resumeController);

/**
 * @route POST / (regular endpoint)
 * @desc Chat with an assistant
 * @access Public
 * @param {express.Request} req - The request object, containing the request data.
 * @param {express.Response} res - The response object, used to send back a response.
 * @returns {void}
 */
router.post('/', controller);

/**
 * @route POST /:endpoint (ephemeral agents)
 * @desc Chat with an assistant
 * @access Public
 * @param {express.Request} req - The request object, containing the request data.
 * @param {express.Response} res - The response object, used to send back a response.
 * @returns {void}
 */
router.post('/:endpoint', controller);

module.exports = router;
