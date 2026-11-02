; Inquiry Desk product-core light web-installer. NONSHIPPING until full Windows and Project tests.
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "WinVer.nsh"
Name "Inquiry Desk (NONSHIPPING)"
OutFile "..\output\InquiryDesk_Setup_P4A_R002_NONSHIPPING.exe"
InstallDir "$LOCALAPPDATA\Programs\InquiryDesk"
RequestExecutionLevel user
ManifestDPIAware true
SetCompressor /SOLID zlib
CRCCheck on
SetDateSave off
ShowInstDetails show
ShowUninstDetails show
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"
Function .onInit
  SetShellVarContext current
  StrCmp $INSTDIR "$LOCALAPPDATA\Programs\InquiryDesk" +3
  MessageBox MB_OK|MB_ICONSTOP "安装位置不可用。此版本仅允许独立的用户程序文件夹。"
  Abort
  ; Never overwrite an older installation before data-safe upgrade receipts exist.
  IfFileExists "$INSTDIR\manifest\SHA256SUMS" 0 +3
  MessageBox MB_OK|MB_ICONSTOP "检测到已有 Inquiry Desk 安装。为保护 Project/Chat/Memory 与回滚能力，本候选禁止直接覆盖更新；请使用经验证的升级入口。"
  Abort
FunctionEnd

!if /FileExists "X:\product\windows\InquiryDesk.ps1"
!else
  !error "P4A_RELEASE_BLOCK_LAUNCH_SCRIPT_NOT_EMBEDDED"
!endif
!if /FileExists "X:\product\windows\InquiryDesk_R227.ps1"
  !error "P4A_RELEASE_BLOCK_LEGACY_LAUNCH_SCRIPT_REFERENCES"
!endif
Section "Inquiry Desk Project Core (required)" Core
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "X:\*"
  CreateDirectory "$INSTDIR\product\overlay\librechat\empty-native-skill"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\Inquiry Desk"
  CreateShortCut "$SMPROGRAMS\Inquiry Desk\打开 Inquiry Desk.lnk" "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\product\windows\InquiryDesk.ps1" -Mode Open'
  CreateShortCut "$DESKTOP\Inquiry Desk.lnk" "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\product\windows\InquiryDesk.ps1" -Mode Open'
  CreateShortCut "$SMPROGRAMS\Inquiry Desk\帮助与安装步骤.lnk" "$INSTDIR\docs\FIRST_RUN.zh-Hans.md"
  CreateShortCut "$SMPROGRAMS\Inquiry Desk\配置 Project 文件检索.lnk" "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\product\windows\InquiryDesk.ps1" -Mode ConfigureFileSearch'
  CreateShortCut "$SMPROGRAMS\Inquiry Desk\卸载 Inquiry Desk.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InquiryDeskP4A" "DisplayName" "Inquiry Desk v0.8.8 (NONSHIPPING)"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InquiryDeskP4A" "DisplayVersion" "0.8.8"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InquiryDeskP4A" "Publisher" "Inquiry Desk (NONSHIPPING)"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InquiryDeskP4A" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InquiryDeskP4A" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InquiryDeskP4A" "NoModify" 1
  DetailPrint "产品核心代码已安装。正在打开环境检查/官方下载安装向导。用户须自行确认供应商许可和授权。"
  Exec '"$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\product\windows\InquiryDesk.ps1" -Mode Open'
SectionEnd
Function un.onInit
  SetShellVarContext current
  StrCmp $INSTDIR "$LOCALAPPDATA\Programs\InquiryDesk" +3
  MessageBox MB_OK|MB_ICONSTOP "卸载已停止：程序目录不属于 Inquiry Desk。"
  Abort
  IfFileExists "$INSTDIR\manifest\SHA256SUMS" +3
  MessageBox MB_OK|MB_ICONSTOP "卸载已停止：软件发行清单缺失。"
  Abort
FunctionEnd
Section "Uninstall"
  ExecWait '"$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\product\windows\InquiryDesk.ps1" -Mode Shutdown' $0
  StrCmp $0 0 +3
  MessageBox MB_OK|MB_ICONSTOP "为保护 Project 数据，停止软件服务失败，暂不卸载。"
  Abort
  Delete "$DESKTOP\Inquiry Desk.lnk"
  Delete "$SMPROGRAMS\Inquiry Desk\打开 Inquiry Desk.lnk"
  Delete "$SMPROGRAMS\Inquiry Desk\帮助与安装步骤.lnk"
  Delete "$SMPROGRAMS\Inquiry Desk\配置 Project 文件检索.lnk"
  Delete "$SMPROGRAMS\Inquiry Desk\卸载 Inquiry Desk.lnk"
  RMDir "$SMPROGRAMS\Inquiry Desk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InquiryDeskP4A"
  !include "R241_EXACT_UNINSTALL_ALLOWLIST.nsh"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
