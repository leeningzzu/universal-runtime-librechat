import { useRecoilCallback } from 'recoil';
import { dataService, QueryKeys, request } from 'librechat-data-provider';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type {
  TChatProject,
  TConversation,
  TCreateChatProjectRequest,
  TDeleteChatProjectResponse,
  TUpdateChatProjectRequest,
  TAssignConversationToProjectRequest,
  TAssignConversationToProjectResponse,
} from 'librechat-data-provider';
import type { QueryClient, UseMutationResult } from '@tanstack/react-query';
import { enqueue, updateConvoInAllQueries, invalidateConversationLists, clearMessagesCache } from '~/utils';
import { getSessionPrincipal } from '~/utils/session';
import store from '~/store';

export const useCreateProjectMutation = (): UseMutationResult<
  TChatProject,
  unknown,
  TCreateChatProjectRequest,
  unknown
> => {
  const queryClient = useQueryClient();
  return useMutation((payload: TCreateChatProjectRequest) => dataService.createProject(payload), {
    onSuccess: () => {
      queryClient.invalidateQueries([QueryKeys.projects]);
    },
  });
};

export const useUpdateProjectMutation = (): UseMutationResult<
  TChatProject,
  unknown,
  TUpdateChatProjectRequest,
  unknown
> => {
  const queryClient = useQueryClient();
  return useMutation((payload: TUpdateChatProjectRequest) => dataService.updateProject(payload), {
    onSuccess: (project) => {
      queryClient.setQueryData([QueryKeys.project, project._id], project);
      queryClient.invalidateQueries([QueryKeys.projects]);
    },
  });
};

/** Exact C5 whole-Project deletion; unlike upstream deleteProject this cannot unassign
 * chats and leave their content behind. One explicit confirmation in the native
 * ProjectDeleteDialog authorizes exactly one prepare and one irreversible DELETE.
 * Unknown outcomes must be checked via the read-only status endpoint, never retried.
 */
export const permanentlyDeleteProjectWithC5 = async (
  projectId: string,
): Promise<TDeleteChatProjectResponse> => {
  if (!/^[a-f0-9]{24}$/i.test(projectId)) {
    throw new Error('C5_PROJECT_ID_INVALID_NO_DELETE');
  }
  const actor = getSessionPrincipal();
  if (!actor) {
    throw new Error('C5_SIGNED_IN_NATIVE_PROJECT_OWNER_REQUIRED');
  }
  // Do not perform a destructive action from an obscured/inactive browser tab.
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
    throw new Error('C5_DELETE_TAB_NOT_ACTIVE_NO_RETRY');
  }
  const path = '/api/projects/' + encodeURIComponent(projectId);
  const protectionMode = 'FORWARD_ONLY_DURABLE_RECEIPT_R001';
  const headers = {
    'Content-Type': 'application/json',
    'x-c5-delete-protection-policy': protectionMode,
  };
  type C5Response = {
    status?: string;
    code?: string;
    projectId?: string;
    operationId?: string;
    wholeProjectCascadeReady?: boolean;
    protectionMode?: string;
    backupCreated?: boolean;
    retryAutomatically?: boolean;
    verified?: boolean;
    userRecoverable?: boolean;
    receiptRevision?: number;
  };
  const requestJson = async (
    url: string,
    init: RequestInit,
  ): Promise<{ ok: boolean; body: C5Response }> => {
    const response = await request.authenticatedFetch(url, { ...init, cache: 'no-store' });
    const body = (await response.json().catch(() => null)) as C5Response | null;
    return { ok: response.ok, body: body ?? {} };
  };

  // PREPARE verifies actual owner, exclusivity, current revision and the durable
  // forward-only recovery proof without writing a new global backup.
  const preparedResponse = await requestJson(path + '/c5-whole-delete/prepare', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      projectId,
      confirmedIrreversibleProjectDelete: true,
      deleteProtectionPolicy: protectionMode,
    }),
  });
  const prepared = preparedResponse.body;
  if (
    !preparedResponse.ok ||
    prepared.status !== 'C5_WHOLE_PROJECT_DELETE_READY' ||
    prepared.projectId !== projectId ||
    prepared.wholeProjectCascadeReady !== true ||
    !/^C5LEASE_[A-Za-z0-9_-]{16,128}$/.test(String(prepared.operationId ?? '')) ||
    prepared.protectionMode !== protectionMode ||
    prepared.backupCreated !== false ||
    prepared.retryAutomatically === true ||
    getSessionPrincipal() !== actor
  ) {
    throw new Error(prepared.code || 'C5_DIRECT_DELETE_PREPARE_UNVERIFIED_NO_RETRY');
  }

  // Exactly ONE effect call. No native deleteProject fallback is lawful here.
  const completedResponse = await requestJson(path, {
    method: 'DELETE',
    headers: {
      ...headers,
      'x-c5-irrevocable-project-delete': 'CONFIRMED_C5_WHOLE_PROJECT_DELETE_R001',
    },
    body: JSON.stringify({
      projectId,
      confirmedIrreversibleProjectDelete: true,
      deleteProtectionPolicy: protectionMode,
      c5PrepareOperationId: prepared.operationId,
    }),
  });
  const completed = completedResponse.body;
  if (
    !completedResponse.ok ||
    completed.status !== 'COMPLETE_VERIFIED_PROJECT_DELETE' ||
    completed.projectId !== projectId ||
    completed.verified !== true ||
    completed.userRecoverable !== false ||
    !Number.isInteger(completed.receiptRevision) ||
    (completed.receiptRevision ?? 0) < 1 ||
    getSessionPrincipal() !== actor
  ) {
    throw new Error(completed.code || 'C5_FULL_PROJECT_DELETE_OUTCOME_UNVERIFIED_NO_RETRY');
  }
  return completed as unknown as TDeleteChatProjectResponse;
};

export const useDeleteProjectMutation = (): UseMutationResult<
  TDeleteChatProjectResponse,
  unknown,
  string,
  unknown
> => {
  const queryClient = useQueryClient();
  const clearDeletedProjectConversationState = useRecoilCallback(
    ({ snapshot, reset }) =>
      async (projectId: string) => {
        const conversation = await snapshot.getPromise(store.conversationByIndex(0));
        if (conversation?.conversationId && conversation.chatProjectId === projectId) {
          // This conversation was permanently deleted, not merely unassigned.
          clearMessagesCache(queryClient, conversation.conversationId);
          reset(store.conversationByIndex(0));
        }
      },
    [queryClient],
  );
  return useMutation((projectId: string) => permanentlyDeleteProjectWithC5(projectId), {
    onSuccess: (_result, projectId) => {
      clearDeletedProjectConversationState(projectId);
      // Evict browser-only message caches; persisted unrelated chats are intact.
      queryClient.removeQueries([QueryKeys.messages]);
      // Invalidate so an *active* project-detail observer refetches and settles into a
      // not-found state — consumers (e.g. ChatRoute) can then react to the deletion.
      // (Removing it instead leaves observers stuck loading under `refetchOnMount: false`.)
      queryClient.invalidateQueries([QueryKeys.project, projectId]);
      // Drop any *inactive* cached detail so a later visit to the deleted project
      // refetches (→ not-found) rather than rendering stale cache within `cacheTime`.
      queryClient.removeQueries([QueryKeys.project, projectId], { type: 'inactive' });
      queryClient.invalidateQueries([QueryKeys.projects]);
      /** Archived rows carry the same project field and menu state. */
      invalidateConversationLists(queryClient);
      /** C5 deletion removes exclusive chats; invalidate all surviving cached listings. */
      queryClient.invalidateQueries([QueryKeys.pinnedConversations]);
    },
  });
};

/** One queue per conversation: assignments to different chats stay independent. */
const ASSIGN_CONVERSATION_QUEUE = 'assign-conversation:';

/** Where each conversation is headed while a write for it is still queued or in
 *  flight, recorded here so every assignment path shares one answer: a drag
 *  helper that tracked only its own writes would keep reporting its
 *  destination after a menu action had moved the chat somewhere else. Each
 *  entry is identified by the write that made it, since comparing destinations
 *  alone cannot tell two moves to the same project apart. */
type PendingAssignment = { token: number; projectId: string | null; owner?: string };

const pendingAssignments = new Map<string, PendingAssignment>();
let assignmentToken = 0;

/** The destination of the newest write still outstanding, if there is one. */
export const getPendingAssignment = (conversationId: string): PendingAssignment | undefined => {
  const pending = pendingAssignments.get(conversationId);
  /* An entry left by another account describes a conversation this session
   * cannot see, so it must not answer for one of its own. */
  return pending && !isForeignSession(pending.owner) ? pending : undefined;
};

const isForeignSession = (owner?: string): boolean =>
  owner == null || getSessionPrincipal() !== owner;

export const useAssignConversationToProjectMutation = (): UseMutationResult<
  TAssignConversationToProjectResponse,
  unknown,
  TAssignConversationToProjectRequest,
  unknown
> => {
  const queryClient = useQueryClient();
  /* Only the project field is published. `updateConversationSelector` spreads
   * whatever it is given over the active conversation, so passing the whole
   * response would also reinstate every other field as the server held it when
   * the assignment ran, undoing a rename that landed in between. */
  const updateActiveConversation = useRecoilCallback(
    ({ set }) =>
      (conversationId: string, chatProjectId: string | null) => {
        set(store.updateConversationSelector(conversationId), { chatProjectId });
      },
    [],
  );

  return useMutation(
    /* Serialized per conversation, and here rather than at any one caller: the
     * drag targets, the row menu and the project dialog each hold their own
     * mutation instance, and the write is an unconditional update, so two of
     * them racing let whichever request reached the database last decide the
     * project regardless of which the user asked for first. */
    (payload: TAssignConversationToProjectRequest) => {
      const { conversationId, projectId } = payload;
      const owner = getSessionPrincipal();
      const token = ++assignmentToken;
      pendingAssignments.set(conversationId, { token, projectId: projectId ?? null, owner });
      return enqueue(`${ASSIGN_CONVERSATION_QUEUE}${owner ?? ''}:${conversationId}`, async () => {
        /* Inside the `try`, so that abandoning the write still releases its
         * pending entry: left behind, it would answer for this conversation
         * again the next time the account signed in, and report a destination
         * that was never sent. */
        try {
          /* A queued write travels with whatever credentials are current when it
           * finally runs. Conversation ids are per-user, so sending one account's
           * under another's would act on whatever that id names over there. */
          if (isForeignSession(owner)) {
            throw new Error('assignment abandoned: the signed-in user changed');
          }
          const result = await dataService.assignConversationToProject(payload);
          if (isForeignSession(owner)) {
            /* The session turned over while the request was out. Rejecting
             * rather than returning, so none of the success path runs: the
             * caches are not scoped by user and conversation ids repeat across
             * accounts, so this answer would otherwise describe one account's
             * conversation to the next, and report success for it. */
            throw new Error('assignment abandoned: the signed-in user changed');
          }
          /* The authoritative cache is written here, before the pending entry is
           * released, so a drag starting in between still sees the new project
           * from one of the two. Doing it in `onSuccess` left a gap while that
           * callback awaited the cancellation, and would not run at all once
           * the component that owns the mutation had unmounted. */
          await queryClient.cancelQueries([QueryKeys.conversation, conversationId]);
          /* Cancelling waits on whatever fetch was already running, so the
           * session can turn over between the check above and the write below.
           * Asked again on this side of the await, where the answer is the one
           * the write is about to act on. */
          if (isForeignSession(owner)) {
            throw new Error('assignment abandoned: the signed-in user changed');
          }
          /* Merged rather than replaced, for the same reason: an assignment that
           * reached the database before a concurrent rename can still answer
           * after it, and its copy of the conversation predates that rename. */
          queryClient.setQueryData<TConversation>(
            [QueryKeys.conversation, conversationId],
            (previous) =>
              previous
                ? { ...previous, chatProjectId: result.conversation.chatProjectId ?? null }
                : result.conversation,
          );
          updateConvoInAllQueries(queryClient, conversationId, (previous) => ({
            ...previous,
            chatProjectId: result.conversation.chatProjectId ?? null,
          }));
          return result;
        } finally {
          /* Only the newest write clears the entry; by now the conversation
           * cache carries the truth, so no list refresh has to be waited on. */
          if (pendingAssignments.get(conversationId)?.token === token) {
            pendingAssignments.delete(conversationId);
          }
        }
      });
    },
    {
      onSuccess: (result) => {
        /* The conversation cache is written in the request itself, above. */
        if (result.conversation.conversationId) {
          updateActiveConversation(
            result.conversation.conversationId,
            result.conversation.chatProjectId ?? null,
          );
        }
        [result.previousProjectId, result.projectId].forEach((projectId) => {
          if (projectId) {
            queryClient.invalidateQueries([QueryKeys.project, projectId]);
          }
        });
        queryClient.invalidateQueries([QueryKeys.projects]);
        /** Archived rows carry the same project field and menu state. */
        invalidateConversationLists(queryClient);
        /** The pinned row carries `chatProjectId` for its options menu. */
        queryClient.invalidateQueries([QueryKeys.pinnedConversations]);
        queryClient.invalidateQueries([QueryKeys.projectConversations]);
      },
    },
  );
};

export type ProjectFileMutationVariables = {
  projectId: string;
  file_id: string;
};

const invalidateProjectFiles = (queryClient: QueryClient, projectId: string): void => {
  queryClient.invalidateQueries({
    queryKey: [QueryKeys.project, projectId],
    refetchType: 'all',
  });
  queryClient.invalidateQueries([QueryKeys.projectFiles, projectId]);
  queryClient.invalidateQueries([QueryKeys.projectAvailableFiles, projectId]);
  queryClient.invalidateQueries([QueryKeys.projects]);
};

export const useAddProjectFileMutation = (): UseMutationResult<
  TChatProject,
  unknown,
  ProjectFileMutationVariables,
  unknown
> => {
  const queryClient = useQueryClient();
  return useMutation(
    ({ projectId, file_id }: ProjectFileMutationVariables) =>
      dataService.addProjectFile({ projectId, file_id }),
    {
      onSuccess: (_project, variables) => invalidateProjectFiles(queryClient, variables.projectId),
    },
  );
};

export const useRemoveProjectFileMutation = (): UseMutationResult<
  TChatProject,
  unknown,
  ProjectFileMutationVariables,
  unknown
> => {
  const queryClient = useQueryClient();
  return useMutation(
    ({ projectId, file_id }: ProjectFileMutationVariables) =>
      dataService.removeProjectFile({ projectId, file_id }),
    {
      onSuccess: (_project, variables) => invalidateProjectFiles(queryClient, variables.projectId),
    },
  );
};
