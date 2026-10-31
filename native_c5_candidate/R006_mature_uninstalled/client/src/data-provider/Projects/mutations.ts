import { useRecoilCallback } from 'recoil';
import { apiBaseUrl, dataService, QueryKeys, request } from 'librechat-data-provider';
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
import type { UseMutationResult } from '@tanstack/react-query';
import { enqueue, invalidateConversationLists } from '~/utils';
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

export const useDeleteProjectMutation = (): UseMutationResult<
  TDeleteChatProjectResponse,
  unknown,
  string,
  unknown
> => {
  const queryClient = useQueryClient();
  return useMutation(async (projectId: string) => {
    // Product consumer refuses to call current upstream unassign-only DELETE.
    // This endpoint is absent until the FULL C5 lifecycle backend is installed.
    // A read-only UI preflight does NOT replace the server's point-of-effect
    // writer/Job, ownership, reference, revision and backup admission checks.
    // User confirmed irreversible Project Delete in ProjectDeleteDialog.
    // Existing Runtime binding is reused; a missing one may be created only
    // by this authenticated POST after actual native Project owner, live
    // Job/writer admission and a fresh protected backup are proven.
    const prepared = (await request.post(
      `${apiBaseUrl()}/api/projects/${encodeURIComponent(projectId)}/c5-whole-delete/prepare`,
      { confirmedIrreversibleProjectDelete: true },
    )) as unknown as {status?:unknown;projectId?:unknown;wholeProjectCascadeReady?:unknown};
    if (prepared?.status !== 'C5_WHOLE_PROJECT_DELETE_READY' ||
        prepared.projectId !== projectId || prepared.wholeProjectCascadeReady !== true) {
      throw new Error('C5_CONFIRMED_NATIVE_PROJECT_PREPARATION_NOT_READY');
    }
    const readiness = (await request.get(
      `${apiBaseUrl()}/api/projects/${encodeURIComponent(projectId)}/c5-whole-delete/readiness`,
    )) as unknown as { status?: unknown; projectId?: unknown; wholeProjectCascadeReady?: unknown };
    if (readiness?.status !== 'C5_WHOLE_PROJECT_DELETE_READY' ||
        readiness.projectId !== projectId || readiness.wholeProjectCascadeReady !== true) {
      throw new Error('C5_WHOLE_PROJECT_DELETE_BACKEND_NOT_READY');
    }
    const reply = await dataService.deleteProject(projectId);
    const result = reply as unknown as {
      status?: unknown; projectId?: unknown; verified?: unknown;
      receiptRevision?: unknown; userRecoverable?: unknown;
    };
    if (result?.status !== 'COMPLETE_VERIFIED_PROJECT_DELETE' ||
        result.projectId !== projectId || result.verified !== true ||
        result.userRecoverable !== false ||
        typeof result.receiptRevision !== 'number' ||
        !Number.isInteger(result.receiptRevision) || result.receiptRevision < 1) {
      // Including upstream 200 { deletedCount, modifiedCount }, HTTP 202
      // PARTIAL and unknown-after-effect. None is a completed user Delete.
      throw new Error('C5_WHOLE_PROJECT_DELETE_NOT_VERIFIED_NO_AUTO_RETRY');
    }
    return reply;
  }, {
    onSuccess: (_result, projectId) => {
      // Upstream unassigning a now-deleted Chat to Project=null is WRONG for
      // irreversible C5. Drop stale Project/Chat and message projections;
      // only a verified full C5 receipt can trigger this cache transition.
      queryClient.invalidateQueries([QueryKeys.conversation]);
      queryClient.invalidateQueries([QueryKeys.messages]);
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
      /** C5 has deleted Project-owned conversations, not unassigned them. */
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
