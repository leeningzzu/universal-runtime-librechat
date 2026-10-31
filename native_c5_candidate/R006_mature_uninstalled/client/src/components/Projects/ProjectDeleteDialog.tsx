import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Button,
  Spinner,
  OGDialog,
  OGDialogClose,
  OGDialogTitle,
  OGDialogHeader,
  OGDialogContent,
  useToastContext,
} from '@librechat/client';
import type { TChatProject } from 'librechat-data-provider';
import { useDeleteProjectMutation } from '~/data-provider';
import { NotificationSeverity } from '~/common';
import { useLocalize } from '~/hooks';

type ProjectDeleteDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  project: TChatProject;
};

export default function ProjectDeleteDialog({
  open,
  onOpenChange,
  project,
}: ProjectDeleteDialogProps) {
  const localize = useLocalize();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const deleteProject = useDeleteProjectMutation();
  const { showToast } = useToastContext();

  const confirmDelete = () => {
    deleteProject.mutate(project._id, {
      onSuccess: () => {
        onOpenChange(false);
        if (location.pathname === `/projects/${project._id}`) {
          navigate('/projects');
        }
      },
      onError: () =>
        showToast({
          message: t('com_ui_c5_project_delete_unverified', {
            defaultValue: 'Permanent deletion could not be verified. The operation may be partially complete; do not retry automatically.',
          }),
          severity: NotificationSeverity.ERROR,
          showIcon: true,
        }),
    });
  };

  return (
    <OGDialog open={open} onOpenChange={onOpenChange}>
      <OGDialogContent className="w-11/12 max-w-md" showCloseButton={false}>
        <OGDialogHeader>
          <OGDialogTitle>{localize('com_ui_delete_project')}</OGDialogTitle>
        </OGDialogHeader>
        {/* C5 User-approved Product contract: Project has no user-side Trash.
            Ordinary Chat/File deletion is a separate 30-day restorable flow. */}
        <div role="alert" className="text-sm text-text-secondary">
          {t('com_ui_c5_project_delete_irrevocable_confirm', {
            name: project.name,
            defaultValue: 'Permanently delete "{{name}}" and its Project-owned chats, messages, instructions, memories, sources and unshared files? This cannot be undone. Chats moved to another Project and shared or Library files are retained.',
          })}
        </div>
        <div className="flex justify-end gap-4 pt-4">
          <OGDialogClose asChild>
            <Button aria-label={localize('com_ui_cancel')} variant="outline">
              {localize('com_ui_cancel')}
            </Button>
          </OGDialogClose>
          <Button variant="destructive" onClick={confirmDelete} disabled={deleteProject.isLoading}>
            {deleteProject.isLoading ? <Spinner className="size-4" /> : localize('com_ui_delete')}
          </Button>
        </div>
      </OGDialogContent>
    </OGDialog>
  );
}
