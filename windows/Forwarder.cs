using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.NetworkInformation;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("转发")]
[assembly: AssemblyDescription("安卓消息通知转发接收端")]
[assembly: AssemblyProduct("转发")]
[assembly: AssemblyCompany("XXZF")]
[assembly: AssemblyVersion("0.3.0.0")]

namespace XXZF.Forwarder
{
    internal static class Program
    {
        private const string MutexName = @"Local\XXZF.Forwarder.SingleInstance";
        private const string ShowEventName = @"Local\XXZF.Forwarder.Show";

        [STAThread]
        private static void Main()
        {
            bool created;
            using (Mutex mutex = new Mutex(true, MutexName, out created))
            {
                if (!created)
                {
                    try { EventWaitHandle.OpenExisting(ShowEventName).Set(); }
                    catch { }
                    return;
                }

                ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
                Application.ThreadException += delegate
                {
                    DiagnosticLogStore.Add("error", "UI_THREAD_FAILURE");
                    MessageBox.Show(
                        "转发遇到错误，请重新打开应用；如仍无法使用，可在应用中上传诊断日志。",
                        "转发",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                };
                try
                {
                    Application.Run(new MainForm(ShowEventName));
                }
                catch
                {
                    DiagnosticLogStore.Add("error", "APP_START_FAILURE");
                    MessageBox.Show(
                        "转发暂时无法启动，请重新打开应用。",
                        "转发",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                }
            }
        }
    }

    internal sealed class ReceiverState
    {
        public string ServerBase { get; set; }
        public string ReceiverId { get; set; }
        public string ProtectedSecret { get; set; }
        public string ReceiverFingerprint { get; set; }
        public string PairingCode { get; set; }
        public string PairingId { get; set; }
        public long PairingExpiresAt { get; set; }
        public bool ShowContent { get; set; }
        public string ContentMode { get; set; }
        public string PairingQrPng { get; set; }
        public int SkippedUpdateVersionCode { get; set; }

        public ReceiverState()
        {
            ShowContent = true;
            ContentMode = "full";
        }
    }

    internal static class StateStore
    {
        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        private static readonly string DirectoryPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "XXZF");
        internal static readonly string StatePath = Path.Combine(DirectoryPath, "windows-receiver.json");
        internal static readonly string CaptureFlagPath = Path.Combine(DirectoryPath, "capture-next");
        internal static readonly string CapturePath = Path.Combine(DirectoryPath, "windows-notification-test.png");

        internal static ReceiverState Load()
        {
            try
            {
                WindowsFileSecurity.EnsurePrivateDirectory(DirectoryPath);
                if (!File.Exists(StatePath)) return new ReceiverState();
                WindowsFileSecurity.RejectReparsePointIfPresent(StatePath);
                WindowsFileSecurity.ProtectFile(StatePath);
                ReceiverState state = Json.Deserialize<ReceiverState>(File.ReadAllText(StatePath, Encoding.UTF8));
                if (state != null && state.ContentMode != "full"
                    && state.ContentMode != "title" && state.ContentMode != "source")
                    state.ContentMode = state.ShowContent ? "full" : "source";
                return state ?? new ReceiverState();
            }
            catch
            {
                return new ReceiverState();
            }
        }

        internal static void Save(ReceiverState state)
        {
            WindowsFileSecurity.EnsurePrivateDirectory(DirectoryPath);
            WindowsFileSecurity.RejectReparsePointIfPresent(StatePath);
            string temporary = StatePath + ".tmp";
            WindowsFileSecurity.RejectReparsePointIfPresent(temporary);
            File.WriteAllText(temporary, Json.Serialize(state), new UTF8Encoding(false));
            WindowsFileSecurity.ProtectFile(temporary);
            if (File.Exists(StatePath)) File.Replace(temporary, StatePath, null);
            else File.Move(temporary, StatePath);
            WindowsFileSecurity.ProtectFile(StatePath);
        }

        internal static string ProtectSecret(string secret)
        {
            byte[] encrypted = ProtectedData.Protect(
                Encoding.UTF8.GetBytes(secret ?? ""), null, DataProtectionScope.CurrentUser);
            return Convert.ToBase64String(encrypted);
        }

        internal static string UnprotectSecret(string protectedSecret)
        {
            try
            {
                byte[] encrypted = Convert.FromBase64String(protectedSecret ?? "");
                return Encoding.UTF8.GetString(ProtectedData.Unprotect(
                    encrypted, null, DataProtectionScope.CurrentUser));
            }
            catch
            {
                return "";
            }
        }
    }

    internal sealed class DiagnosticEntry
    {
        public long at { get; set; }
        public string level { get; set; }
        public string code { get; set; }
        public int httpStatus { get; set; }
    }

    internal sealed class ApiException : Exception
    {
        internal int StatusCode { get; private set; }

        internal ApiException(int statusCode, string message) : base(message)
        {
            StatusCode = statusCode;
        }
    }

    internal static class DiagnosticLogStore
    {
        private static readonly object Sync = new object();
        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        private static readonly string PathValue = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "XXZF", "windows-diagnostics.json");

        internal static void Add(string level, string code, int httpStatus = 0)
        {
            lock (Sync)
            {
                List<DiagnosticEntry> entries = Load();
                string safeCode = Regex.Replace(
                    (code ?? "UNKNOWN").ToUpperInvariant(), "[^A-Z0-9_.:-]", "_");
                if (safeCode.Length == 0) safeCode = "UNKNOWN";
                if (safeCode.Length > 48) safeCode = safeCode.Substring(0, 48);
                entries.Insert(0, new DiagnosticEntry {
                    at = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    level = level == "warning" || level == "error" ? level : "info",
                    code = safeCode,
                    httpStatus = Math.Max(0, Math.Min(999, httpStatus))
                });
                if (entries.Count > 80) entries.RemoveRange(80, entries.Count - 80);
                WindowsFileSecurity.EnsurePrivateDirectory(Path.GetDirectoryName(PathValue));
                WindowsFileSecurity.RejectReparsePointIfPresent(PathValue);
                WindowsFileSecurity.RejectReparsePointIfPresent(PathValue + ".tmp");
                File.WriteAllText(PathValue + ".tmp", Json.Serialize(entries), new UTF8Encoding(false));
                WindowsFileSecurity.ProtectFile(PathValue + ".tmp");
                if (File.Exists(PathValue)) File.Replace(PathValue + ".tmp", PathValue, null);
                else File.Move(PathValue + ".tmp", PathValue);
                WindowsFileSecurity.ProtectFile(PathValue);
            }
        }

        internal static List<DiagnosticEntry> Load()
        {
            try
            {
                if (!File.Exists(PathValue)) return new List<DiagnosticEntry>();
                WindowsFileSecurity.RejectReparsePointIfPresent(PathValue);
                WindowsFileSecurity.ProtectFile(PathValue);
                return Json.Deserialize<List<DiagnosticEntry>>(File.ReadAllText(PathValue, Encoding.UTF8))
                    ?? new List<DiagnosticEntry>();
            }
            catch { return new List<DiagnosticEntry>(); }
        }
    }

    internal sealed class MainForm : Form
    {
        private const string OfficialServer = "https://example.com/xxzf";
        private const string CredentialRecoveryButtonText = "清除失效凭据并重配";
        private static readonly Color Ink = Color.FromArgb(25, 29, 36);
        private static readonly Color Muted = Color.FromArgb(104, 112, 124);
        private static readonly Color Surface = Color.White;
        private static readonly Color Canvas = Color.FromArgb(246, 247, 249);
        private static readonly Color Green = Color.FromArgb(28, 142, 83);
        private static readonly Color Red = Color.FromArgb(210, 67, 61);
        private static readonly Color Blue = Color.FromArgb(25, 121, 214);

        private readonly JavaScriptSerializer json = new JavaScriptSerializer();
        private readonly ReceiverState state;
        private readonly NotifyIcon trayIcon;
        private readonly EventWaitHandle showEvent;
        private readonly CancellationTokenSource lifetime = new CancellationTokenSource();
        private readonly HashSet<string> delivered = new HashSet<string>();
        private readonly UpdateManager updateManager = new UpdateManager();

        private Label statusDot;
        private Label statusText;
        private Label detailText;
        private Label codeText;
        private Label expiryText;
        private Label lastEventText;
        private PictureBox qrBox;
        private Button[] contentButtons;
        private Button pairButton;
        private Button testButton;
        private Button diagnosticButton;
        private Label diagnosticResult;
        private Button updateButton;
        private Label updateStatus;
        private System.Windows.Forms.Timer healthTimer;
        private System.Windows.Forms.Timer updateTimer;
        private string serverStatusCode = "unknown";
        private bool exiting;
        private bool awaitingPairing;
        private bool credentialRecoveryRequired;
        private bool updateCheckInProgress;
        private Task receiverTask;

        internal MainForm(string showEventName)
        {
            state = StateStore.Load();
            if (!String.Equals(state.ServerBase, OfficialServer, StringComparison.Ordinal))
            {
                state.ServerBase = OfficialServer;
                StateStore.Save(state);
            }
            showEvent = new EventWaitHandle(false, EventResetMode.AutoReset, showEventName);
            BuildWindow();
            trayIcon = BuildTrayIcon();
            StartShowListener();

            healthTimer = new System.Windows.Forms.Timer();
            healthTimer.Interval = 15000;
            healthTimer.Tick += async delegate { await RefreshServerStatusAsync(); };
            healthTimer.Start();

            updateTimer = new System.Windows.Forms.Timer();
            updateTimer.Interval = 6 * 60 * 60 * 1000;
            updateTimer.Tick += async delegate { await CheckForUpdatesAsync(false); };
            updateTimer.Start();
            DiagnosticLogStore.Add("info", "APP_STARTED");

            Shown += async delegate
            {
                try
                {
                    FitWindowToWorkingArea();
                    await RefreshServerStatusAsync();
                    await BeginStartupAsync();
                    await CheckForUpdatesAsync(false);
                }
                catch
                {
                    DiagnosticLogStore.Add("error", "STARTUP_FLOW_FAILED");
                    SetStatus("启动未完成", Red, "请检查网络后重新打开应用");
                }
            };
            FormClosing += HandleFormClosing;
            FormClosed += delegate
            {
                lifetime.Cancel();
                healthTimer.Stop();
                healthTimer.Dispose();
                updateTimer.Stop();
                updateTimer.Dispose();
                trayIcon.Visible = false;
                trayIcon.Dispose();
                showEvent.Dispose();
            };
        }

        private void BuildWindow()
        {
            Text = "转发";
            AutoScaleMode = AutoScaleMode.Dpi;
            AutoScaleDimensions = new SizeF(96F, 96F);
            ClientSize = new Size(460, 820);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Canvas;
            Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular, GraphicsUnit.Point);
            AutoScroll = true;
            MaximizeBox = false;
            Icon = LoadAppIcon();

            PictureBox logo = new PictureBox();
            logo.Location = new Point(32, 28);
            logo.Size = new Size(56, 56);
            logo.SizeMode = PictureBoxSizeMode.Zoom;
            logo.Image = Icon.ToBitmap();
            Controls.Add(logo);

            Label title = NewLabel("转发", 26F, FontStyle.Bold, Ink);
            title.Location = new Point(104, 28);
            title.Size = new Size(300, 38);
            Controls.Add(title);

            Label subtitle = NewLabel("接收设备 · 接收通知", 10F, FontStyle.Regular, Muted);
            subtitle.Location = new Point(106, 66);
            subtitle.Size = new Size(300, 24);
            Controls.Add(subtitle);

            Panel statusPanel = NewPanel(new Point(28, 112), new Size(404, 78));
            statusDot = NewLabel("●", 12F, FontStyle.Regular, Muted);
            statusDot.Location = new Point(18, 15);
            statusDot.Size = new Size(24, 25);
            statusPanel.Controls.Add(statusDot);

            statusText = NewLabel("正在检查连接", 12F, FontStyle.Bold, Ink);
            statusText.Location = new Point(46, 13);
            statusText.Size = new Size(330, 27);
            statusPanel.Controls.Add(statusText);

            detailText = NewLabel("通知服务", 9F, FontStyle.Regular, Muted);
            detailText.Location = new Point(47, 43);
            detailText.Size = new Size(330, 22);
            statusPanel.Controls.Add(detailText);
            Controls.Add(statusPanel);

            Panel pairingPanel = NewPanel(new Point(28, 206), new Size(404, 228));
            Label pairingTitle = NewLabel("设备连接", 11F, FontStyle.Bold, Ink);
            pairingTitle.Location = new Point(18, 16);
            pairingTitle.Size = new Size(160, 26);
            pairingPanel.Controls.Add(pairingTitle);

            codeText = NewLabel("------", 25F, FontStyle.Bold, Ink);
            codeText.Location = new Point(16, 48);
            codeText.Size = new Size(205, 43);
            codeText.TextAlign = ContentAlignment.MiddleLeft;
            pairingPanel.Controls.Add(codeText);

            expiryText = NewLabel("正在读取设备状态", 9F, FontStyle.Regular, Muted);
            expiryText.Location = new Point(18, 99);
            expiryText.Size = new Size(205, 48);
            pairingPanel.Controls.Add(expiryText);

            pairButton = NewButton("生成配对码", false);
            pairButton.Location = new Point(18, 166);
            pairButton.Size = new Size(205, 40);
            pairButton.Click += async delegate { await BeginPairingOrRecoveryAsync(); };
            pairingPanel.Controls.Add(pairButton);

            qrBox = new PictureBox();
            qrBox.Location = new Point(242, 46);
            qrBox.Size = new Size(144, 144);
            qrBox.SizeMode = PictureBoxSizeMode.Zoom;
            qrBox.BackColor = Color.White;
            qrBox.Image = Icon.ToBitmap();
            pairingPanel.Controls.Add(qrBox);
            Controls.Add(pairingPanel);

            Panel settingsPanel = NewPanel(new Point(28, 450), new Size(404, 96));
            Label privacyTitle = NewLabel("本机显示", 10F, FontStyle.Bold, Ink);
            privacyTitle.Location = new Point(18, 10);
            privacyTitle.Size = new Size(150, 24);
            settingsPanel.Controls.Add(privacyTitle);
            string[] labels = new string[] { "完整", "仅标题", "仅来源" };
            string[] modes = new string[] { "full", "title", "source" };
            contentButtons = new Button[3];
            for (int index = 0; index < 3; index++)
            {
                string selectedMode = modes[index];
                Button button = NewButton(labels[index], false);
                button.Location = new Point(18 + index * 122, 42);
                button.Size = new Size(116, 38);
                button.Click += delegate { SetContentMode(selectedMode, true); };
                contentButtons[index] = button;
                settingsPanel.Controls.Add(button);
            }
            Controls.Add(settingsPanel);

            Panel updatePanel = NewPanel(new Point(28, 562), new Size(404, 86));
            Label updateTitle = NewLabel("软件更新", 10F, FontStyle.Bold, Ink);
            updateTitle.Location = new Point(18, 12);
            updateTitle.Size = new Size(100, 24);
            updatePanel.Controls.Add(updateTitle);

            updateStatus = NewLabel("当前版本 " + UpdateManager.CurrentVersion, 8.5F, FontStyle.Regular, Muted);
            updateStatus.Location = new Point(18, 44);
            updateStatus.Size = new Size(220, 24);
            updatePanel.Controls.Add(updateStatus);

            updateButton = NewButton("检查更新", true);
            updateButton.Location = new Point(264, 21);
            updateButton.Size = new Size(120, 42);
            updateButton.Click += async delegate { await CheckForUpdatesAsync(true); };
            updatePanel.Controls.Add(updateButton);
            Controls.Add(updatePanel);

            testButton = NewButton("测试系统通知", true);
            testButton.Location = new Point(28, 664);
            testButton.Size = new Size(196, 42);
            testButton.Click += delegate { ShowTestNotification(false); };
            Controls.Add(testButton);

            diagnosticButton = NewButton("上传诊断日志", false);
            diagnosticButton.Location = new Point(236, 664);
            diagnosticButton.Size = new Size(196, 42);
            diagnosticButton.Click += async delegate { await UploadDiagnosticsAsync(); };
            Controls.Add(diagnosticButton);

            Label diagnosticPrivacy = NewLabel(
                "仅上传连接状态和错误代码，不包含通知正文或设备识别信息",
                8.5F, FontStyle.Regular, Muted);
            diagnosticPrivacy.Location = new Point(30, 716);
            diagnosticPrivacy.Size = new Size(398, 24);
            diagnosticPrivacy.TextAlign = ContentAlignment.MiddleCenter;
            Controls.Add(diagnosticPrivacy);

            diagnosticResult = NewLabel("", 8.5F, FontStyle.Regular, Muted);
            diagnosticResult.Location = new Point(30, 742);
            diagnosticResult.Size = new Size(398, 24);
            diagnosticResult.TextAlign = ContentAlignment.MiddleCenter;
            Controls.Add(diagnosticResult);

            lastEventText = NewLabel("等待第一条通知", 9F, FontStyle.Regular, Muted);
            lastEventText.Location = new Point(30, 784);
            lastEventText.Size = new Size(398, 28);
            lastEventText.TextAlign = ContentAlignment.MiddleCenter;
            Controls.Add(lastEventText);
            UpdateContentModeButtons();
        }

        private void FitWindowToWorkingArea()
        {
            Rectangle workingArea = Screen.FromControl(this).WorkingArea;
            int maximumHeight = Math.Max(620, workingArea.Height - 24);
            if (Height > maximumHeight) Height = maximumHeight;
            Location = new Point(
                workingArea.Left + Math.Max(0, (workingArea.Width - Width) / 2),
                workingArea.Top + Math.Max(0, (workingArea.Height - Height) / 2));
        }

        private NotifyIcon BuildTrayIcon()
        {
            ContextMenuStrip menu = new ContextMenuStrip();
            ToolStripMenuItem open = new ToolStripMenuItem("打开转发");
            open.Click += delegate { ShowWindow(); };
            menu.Items.Add(open);

            ToolStripMenuItem display = new ToolStripMenuItem("本机显示");
            string[] labels = new string[] { "完整", "仅标题", "仅来源" };
            string[] modes = new string[] { "full", "title", "source" };
            for (int index = 0; index < modes.Length; index++)
            {
                string selectedMode = modes[index];
                ToolStripMenuItem mode = new ToolStripMenuItem(labels[index]);
                mode.Name = "mode-" + selectedMode;
                mode.Click += delegate { SetContentMode(selectedMode, true); };
                display.DropDownItems.Add(mode);
            }
            menu.Items.Add(display);

            ToolStripMenuItem checkUpdate = new ToolStripMenuItem("检查更新");
            checkUpdate.Click += async delegate { await CheckForUpdatesAsync(true); };
            menu.Items.Add(checkUpdate);
            menu.Items.Add(new ToolStripSeparator());

            ToolStripMenuItem exit = new ToolStripMenuItem("退出");
            exit.Click += delegate
            {
                exiting = true;
                Close();
            };
            menu.Items.Add(exit);

            NotifyIcon icon = new NotifyIcon();
            icon.Icon = Icon;
            icon.Text = "转发";
            icon.Visible = true;
            icon.ContextMenuStrip = menu;
            icon.DoubleClick += delegate { ShowWindow(); };
            return icon;
        }

        private void UpdateTrayMenu()
        {
            ToolStripMenuItem display = trayIcon.ContextMenuStrip.Items[1] as ToolStripMenuItem;
            if (display == null) return;
            foreach (ToolStripItem child in display.DropDownItems)
            {
                ToolStripMenuItem item = child as ToolStripMenuItem;
                if (item != null) item.Checked = item.Name == "mode-" + state.ContentMode;
            }
        }

        private void SetContentMode(string mode, bool confirm)
        {
            if (mode != "full" && mode != "title" && mode != "source") return;
            state.ContentMode = mode;
            state.ShowContent = mode != "source";
            StateStore.Save(state);
            UpdateContentModeButtons();
            if (trayIcon != null) UpdateTrayMenu();
            if (confirm)
            {
                string message = mode == "full" ? "设置成功：显示标题和正文"
                    : mode == "title" ? "设置成功：仅显示标题"
                    : "设置成功：仅显示来源 App";
                ShowConfirmation(message);
            }
        }

        private void UpdateContentModeButtons()
        {
            if (contentButtons == null) return;
            string[] modes = new string[] { "full", "title", "source" };
            for (int index = 0; index < contentButtons.Length; index++)
            {
                bool selected = state.ContentMode == modes[index];
                contentButtons[index].BackColor = selected ? Blue : Color.FromArgb(238, 245, 253);
                contentButtons[index].ForeColor = selected ? Color.White : Blue;
                contentButtons[index].FlatAppearance.BorderSize = 1;
                contentButtons[index].FlatAppearance.BorderColor = selected ? Blue : Color.FromArgb(190, 213, 240);
            }
        }

        private async Task CheckForUpdatesAsync(bool manual)
        {
            if (updateCheckInProgress) return;
            updateCheckInProgress = true;
            updateButton.Enabled = false;
            updateStatus.ForeColor = Muted;
            updateStatus.Text = "正在安全检查更新";
            try
            {
                if (!NetworkInterface.GetIsNetworkAvailable())
                {
                    updateStatus.Text = "无网络连接";
                    if (manual) ShowConfirmation("无网络连接，暂时无法检查更新");
                    return;
                }

                UpdateCheckResult result = await updateManager.CheckAsync(lifetime.Token);
                if (result.Kind == UpdateCheckKind.Current)
                {
                    updateStatus.ForeColor = Green;
                    updateStatus.Text = result.Message;
                    if (manual) ShowConfirmation(result.Message);
                    DiagnosticLogStore.Add("info", "UPDATE_CURRENT");
                    return;
                }
                if (result.Kind == UpdateCheckKind.Failed)
                {
                    updateStatus.ForeColor = Red;
                    updateStatus.Text = result.Message;
                    DiagnosticLogStore.Add("warning", "UPDATE_CHECK_FAILED");
                    if (manual) ShowConfirmation(result.Message);
                    return;
                }

                UpdateManifest manifest = result.Manifest;
                if (!manual && state.SkippedUpdateVersionCode == manifest.VersionCode)
                {
                    updateStatus.ForeColor = Muted;
                    updateStatus.Text = "已跳过版本 " + manifest.Version;
                    return;
                }

                updateStatus.ForeColor = Blue;
                updateStatus.Text = result.Message;
                trayIcon.BalloonTipTitle = "转发可更新";
                trayIcon.BalloonTipText = "新版本 " + manifest.Version + " 已通过签名校验";
                trayIcon.BalloonTipIcon = ToolTipIcon.Info;
                trayIcon.ShowBalloonTip(5000);
                await PromptAndInstallUpdateAsync(manifest);
            }
            catch (OperationCanceledException)
            {
                updateStatus.Text = "更新检查已取消";
            }
            catch (Exception)
            {
                updateStatus.ForeColor = Red;
                updateStatus.Text = "更新处理失败";
                DiagnosticLogStore.Add("error", "UPDATE_FLOW_FAILED");
                if (manual) ShowConfirmation("更新处理失败，请稍后再试");
            }
            finally
            {
                updateCheckInProgress = false;
                if (!IsDisposed) updateButton.Enabled = true;
            }
        }

        private async Task PromptAndInstallUpdateAsync(UpdateManifest manifest)
        {
            string notes = String.IsNullOrWhiteSpace(manifest.Notes)
                ? "包含安全与稳定性更新。" : manifest.Notes;
            DialogResult answer = MessageBox.Show(
                this,
                "发现新版本 " + manifest.Version + "\r\n\r\n"
                    + TrimTo(notes, 300) + "\r\n\r\n"
                    + "“是”立即下载并更新；“否”跳过此版本；“取消”稍后提醒。\r\n"
                    + "安装包会先完成 RSA 签名、大小和 SHA-256 校验。",
                "转发软件更新",
                MessageBoxButtons.YesNoCancel,
                MessageBoxIcon.Information,
                MessageBoxDefaultButton.Button1);

            if (answer == DialogResult.No)
            {
                state.SkippedUpdateVersionCode = manifest.VersionCode;
                StateStore.Save(state);
                updateStatus.ForeColor = Muted;
                updateStatus.Text = "已跳过版本 " + manifest.Version;
                DiagnosticLogStore.Add("info", "UPDATE_SKIPPED");
                return;
            }
            if (answer != DialogResult.Yes)
            {
                updateStatus.ForeColor = Muted;
                updateStatus.Text = "稍后提醒版本 " + manifest.Version;
                return;
            }

            updateButton.Enabled = false;
            updateStatus.ForeColor = Blue;
            updateStatus.Text = "正在下载并校验 0%";
            await updateManager.DownloadAndLaunchAsync(
                manifest,
                delegate(int percent)
                {
                    try
                    {
                        BeginInvoke((Action)delegate
                        {
                            updateStatus.Text = "正在下载并校验 " + percent + "%";
                        });
                    }
                    catch { }
                },
                lifetime.Token);
            DiagnosticLogStore.Add("info", "UPDATE_INSTALLER_STARTED");
            updateStatus.ForeColor = Green;
            updateStatus.Text = "安装程序已启动";
            exiting = true;
            trayIcon.Visible = false;
            Application.Exit();
        }

        private void ShowConfirmation(string message)
        {
            if (trayIcon == null) return;
            trayIcon.BalloonTipTitle = "转发";
            trayIcon.BalloonTipText = message;
            trayIcon.BalloonTipIcon = ToolTipIcon.Info;
            trayIcon.ShowBalloonTip(2500);
            lastEventText.Text = message;
            lastEventText.ForeColor = Green;
        }

        private void StartShowListener()
        {
            Thread thread = new Thread(delegate()
            {
                while (!lifetime.IsCancellationRequested)
                {
                    if (showEvent.WaitOne(1000))
                    {
                        try { BeginInvoke((Action)ShowWindow); }
                        catch { return; }
                    }
                }
            });
            thread.IsBackground = true;
            thread.Start();
        }

        private void ShowWindow()
        {
            Show();
            WindowState = FormWindowState.Normal;
            Activate();
            BringToFront();
        }

        private void HandleFormClosing(object sender, FormClosingEventArgs eventArgs)
        {
            if (exiting || eventArgs.CloseReason == CloseReason.WindowsShutDown) return;
            eventArgs.Cancel = true;
            Hide();
            trayIcon.BalloonTipTitle = "转发仍在运行";
            trayIcon.BalloonTipText = "有新通知时会继续提醒";
            trayIcon.ShowBalloonTip(3000);
        }

        private async Task BeginStartupAsync()
        {
            if (HasCredential())
            {
                bool paired = await CheckPairingStatusAsync();
                if (paired)
                {
                    ShowPairedState();
                    StartReceiver();
                    return;
                }
                if (credentialRecoveryRequired)
                {
                    MarkAuthenticationFailed(401);
                    return;
                }
                if (state.PairingExpiresAt > CurrentMilliseconds() && !String.IsNullOrEmpty(state.PairingCode))
                {
                    ShowPendingState();
                    BeginPairingPoll();
                    return;
                }
            }
            await StartPairingAsync();
        }

        private async Task BeginPairingOrRecoveryAsync()
        {
            if (HasCredential() && credentialRecoveryRequired)
            {
                DialogResult answer = MessageBox.Show(
                    this,
                    "服务器已拒绝这台 Windows 的设备凭据。\r\n\r\n"
                        + "只有你确认后，应用才会清除本机失效凭据并重新配对；"
                        + "不会静默切换为匿名连接。",
                    "清除失效凭据并重新配对？",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Warning,
                    MessageBoxDefaultButton.Button2);
                if (answer != DialogResult.Yes) return;

                if (!ClearLocalCredentialForRecovery())
                {
                    MessageBox.Show(this, "本机凭据清除失败，原凭据已保留。",
                        "重新配对失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    MarkAuthenticationFailed(401);
                    return;
                }
                DiagnosticLogStore.Add("warning", "CREDENTIAL_RESET_CONFIRMED");
                exiting = true;
                Application.Restart();
                Application.Exit();
                return;
            }
            await StartPairingAsync();
        }

        private bool ClearLocalCredentialForRecovery()
        {
            string oldServer = state.ServerBase;
            string oldReceiverId = state.ReceiverId;
            string oldProtectedSecret = state.ProtectedSecret;
            string oldFingerprint = state.ReceiverFingerprint;
            string oldPairingCode = state.PairingCode;
            string oldPairingId = state.PairingId;
            string oldPairingQr = state.PairingQrPng;
            long oldPairingExpiry = state.PairingExpiresAt;
            try
            {
                state.ServerBase = OfficialServer;
                state.ReceiverId = "";
                state.ProtectedSecret = "";
                state.ReceiverFingerprint = "";
                state.PairingCode = "";
                state.PairingId = "";
                state.PairingQrPng = "";
                state.PairingExpiresAt = 0;
                StateStore.Save(state);
                credentialRecoveryRequired = false;
                return true;
            }
            catch
            {
                state.ServerBase = oldServer;
                state.ReceiverId = oldReceiverId;
                state.ProtectedSecret = oldProtectedSecret;
                state.ReceiverFingerprint = oldFingerprint;
                state.PairingCode = oldPairingCode;
                state.PairingId = oldPairingId;
                state.PairingQrPng = oldPairingQr;
                state.PairingExpiresAt = oldPairingExpiry;
                return false;
            }
        }

        private bool HasCredential()
        {
            return !String.IsNullOrEmpty(state.ReceiverId)
                && !String.IsNullOrEmpty(StateStore.UnprotectSecret(state.ProtectedSecret));
        }

        private async Task StartPairingAsync()
        {
            if (HasCredential() && credentialRecoveryRequired)
            {
                MarkAuthenticationFailed(401);
                return;
            }
            pairButton.Enabled = false;
            expiryText.Text = "正在创建安全配对码";
            Exception last = null;
            foreach (string server in CandidateServers())
            {
                try
                {
                    Dictionary<string, object> request = new Dictionary<string, object>();
                    request["deviceName"] = Environment.MachineName + " 的 Windows";
                    request["platform"] = "windows";
                    string existingBearer = HasCredential()
                        ? state.ReceiverId + "." + StateStore.UnprotectSecret(state.ProtectedSecret)
                        : null;
                    Dictionary<string, object> response = await PostJsonAsync(
                        BuildUrl(server, "pair/start"), request, existingBearer, 8);
                    Dictionary<string, object> pairing = response["pairing"] as Dictionary<string, object>;
                    if (pairing == null) throw new InvalidDataException("配对响应无效");

                    state.ServerBase = server;
                    state.ReceiverId = FirstNonEmpty(Value(pairing, "receiverId"), state.ReceiverId);
                    string newSecret = Value(pairing, "receiverSecret");
                    if (!String.IsNullOrEmpty(newSecret))
                        state.ProtectedSecret = StateStore.ProtectSecret(newSecret);
                    state.ReceiverFingerprint = Value(pairing, "receiverFingerprint");
                    state.PairingCode = Value(pairing, "code");
                    state.PairingId = Value(pairing, "pairingId");
                    state.PairingQrPng = Value(pairing, "qrPng");
                    state.PairingExpiresAt = Convert.ToInt64(pairing["expiresAt"]);
                    awaitingPairing = true;
                    DiagnosticLogStore.Add("info", "PAIRING_CODE_CREATED");
                    StateStore.Save(state);
                    ShowPendingState();
                    BeginPairingPoll();
                    pairButton.Enabled = true;
                    return;
                }
                catch (Exception error)
                {
                    last = error;
                }
            }
            pairButton.Enabled = true;
            DiagnosticLogStore.Add("error", "PAIRING_CODE_FAILED", StatusCode(last));
            expiryText.Text = "生成失败 · " + FriendlyError(last);
            await RefreshServerStatusAsync();
        }

        private void BeginPairingPoll()
        {
            Task.Run(async delegate
            {
                while (!lifetime.IsCancellationRequested && CurrentMilliseconds() < state.PairingExpiresAt)
                {
                    bool paired = await CheckPairingStatusAsync();
                    if (paired)
                    {
                        BeginInvoke((Action)delegate
                        {
                            ShowPairedState();
                            StartReceiver();
                        });
                        return;
                    }
                    if (credentialRecoveryRequired) return;
                    await Task.Delay(1500);
                }
                if (!lifetime.IsCancellationRequested)
                {
                    BeginInvoke((Action)delegate
                    {
                        DiagnosticLogStore.Add("warning", "PAIRING_CODE_EXPIRED");
                        expiryText.Text = "配对码有效期为 5 分钟";
                    });
                }
            });
        }

        private async Task<bool> CheckPairingStatusAsync()
        {
            if (!HasCredential()) return false;
            string bearer = state.ReceiverId + "." + StateStore.UnprotectSecret(state.ProtectedSecret);
            foreach (string server in CandidateServers())
            {
                try
                {
                    string statusUrl = BuildUrl(server, "pair/status");
                    if (!String.IsNullOrEmpty(state.PairingId))
                        statusUrl += "?pairingId=" + Uri.EscapeDataString(state.PairingId);
                    Dictionary<string, object> response = await GetJsonAsync(statusUrl, bearer, 6);
                    object paired;
                    if (response.TryGetValue("paired", out paired) && Convert.ToBoolean(paired))
                    {
                        state.ServerBase = server;
                        StateStore.Save(state);
                        return true;
                    }
                }
                catch (ApiException error)
                {
                    if (error.StatusCode == 401 || error.StatusCode == 403)
                    {
                        MarkAuthenticationFailed(error.StatusCode);
                        return false;
                    }
                }
                catch { }
            }
            return false;
        }

        private void ShowPendingState()
        {
            codeText.Text = FormatCode(state.PairingCode);
            codeText.Font = new Font(Font.FontFamily, 25F, FontStyle.Bold);
            codeText.ForeColor = Ink;
            expiryText.Text = "有效期 5 分钟 · 密钥 " + state.ReceiverFingerprint;
            pairButton.Text = "重新生成";
            SetQrImage(DecodeQrPng(state.PairingQrPng));
        }

        private void ShowPairedState()
        {
            credentialRecoveryRequired = false;
            state.PairingCode = "";
            state.PairingId = "";
            state.PairingQrPng = "";
            state.PairingExpiresAt = 0;
            StateStore.Save(state);
            codeText.Text = "已配对";
            codeText.Font = new Font(Font.FontFamily, 21F, FontStyle.Bold);
            codeText.ForeColor = Green;
            expiryText.Text = "设备编号 " + state.ReceiverFingerprint;
            pairButton.Text = "连接另一台手机";
            SetQrImage(Icon.ToBitmap());
            if (awaitingPairing)
            {
                awaitingPairing = false;
                DiagnosticLogStore.Add("info", "PAIRING_SUCCEEDED");
                ShowConfirmation("配对成功：这台电脑将接收通知");
            }
        }

        private void StartReceiver()
        {
            if (receiverTask != null && !receiverTask.IsCompleted) return;
            receiverTask = Task.Run((Func<Task>)ReceiverLoopAsync);
        }

        private async Task ReceiverLoopAsync()
        {
            string bearer = state.ReceiverId + "." + StateStore.UnprotectSecret(state.ProtectedSecret);
            while (!lifetime.IsCancellationRequested)
            {
                Exception last = null;
                foreach (string server in CandidateServers())
                {
                    try
                    {
                        await StreamServerAsync(server, bearer);
                    }
                    catch (Exception error)
                    {
                        last = error;
                        DiagnosticLogStore.Add("warning", "STREAM_DISCONNECTED", StatusCode(error));
                    }
                    if (lifetime.IsCancellationRequested) return;
                }
                if (!NetworkInterface.GetIsNetworkAvailable())
                    SetStatusThreadSafe("无网络连接", Red, "网络恢复后会自动重连");
                else if (last is ApiException && (((ApiException)last).StatusCode == 401
                    || ((ApiException)last).StatusCode == 403))
                {
                    MarkAuthenticationFailed(((ApiException)last).StatusCode);
                    return;
                }
                else
                    SetStatusThreadSafe("服务器不可用", Red, "稍后自动重试");
                await Task.Delay(2000);
            }
        }

        private async Task StreamServerAsync(string server, string bearer)
        {
            using (HttpClient client = NewClient(bearer, Timeout.InfiniteTimeSpan))
            {
                client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
                using (HttpResponseMessage response = await client.GetAsync(
                    BuildUrl(server, "v1/events"), HttpCompletionOption.ResponseHeadersRead,
                    lifetime.Token).ConfigureAwait(false))
                {
                    if (!response.IsSuccessStatusCode)
                        throw new ApiException((int)response.StatusCode, response.ReasonPhrase);
                    state.ServerBase = server;
                    StateStore.Save(state);
                    serverStatusCode = "online";
                    DiagnosticLogStore.Add("info", "STREAM_CONNECTED", (int)response.StatusCode);
                    SetStatusThreadSafe("服务器在线", Green, ServerLabel());
                    using (Stream stream = await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                    using (StreamReader reader = new StreamReader(stream, Encoding.UTF8))
                    {
                        string eventName = "";
                        StringBuilder data = new StringBuilder();
                        while (!lifetime.IsCancellationRequested)
                        {
                            string line = await reader.ReadLineAsync().ConfigureAwait(false);
                            if (line == null) throw new IOException("连接已关闭");
                            if (line.Length == 0)
                            {
                                if (eventName == "notify" && data.Length > 0)
                                {
                                    Dictionary<string, object> notification =
                                        json.Deserialize<Dictionary<string, object>>(data.ToString());
                                    BeginInvoke((Action)delegate { Deliver(notification); });
                                }
                                eventName = "";
                                data.Length = 0;
                            }
                            else if (line.StartsWith("event:")) eventName = line.Substring(6).Trim();
                            else if (line.StartsWith("data:"))
                            {
                                if (data.Length > 0) data.Append('\n');
                                data.Append(line.Substring(5).Trim());
                            }
                        }
                    }
                }
            }
        }

        private void Deliver(Dictionary<string, object> notification)
        {
            string id = Value(notification, "id") + "|" + Value(notification, "postTime");
            if (delivered.Contains(id)) return;
            delivered.Add(id);
            if (delivered.Count > 200) delivered.Clear();

            string app = FirstNonEmpty(Value(notification, "appName"), Value(notification, "packageName"), "Android");
            string sourceTitle = Value(notification, "title");
            string sourceText = CleanRepeatedTitle(sourceTitle, Value(notification, "text"));
            string privacy = FirstNonEmpty(Value(notification, "privacyMode"), "full");
            string effectivePrivacy = PrivacyRank(state.ContentMode) <= PrivacyRank(privacy)
                ? state.ContentMode : privacy;
            string body = "";
            if (effectivePrivacy != "source")
            {
                body = sourceTitle;
                if (effectivePrivacy == "full" && !String.IsNullOrWhiteSpace(sourceText))
                    body = String.IsNullOrWhiteSpace(body) ? sourceText : body + Environment.NewLine + sourceText;
            }

            trayIcon.BalloonTipTitle = TrimTo("转发：" + app, 63);
            trayIcon.BalloonTipText = String.IsNullOrWhiteSpace(body) ? "\u200B" : TrimTo(body, 220);
            trayIcon.BalloonTipIcon = ToolTipIcon.None;
            trayIcon.ShowBalloonTip(10000);
            lastEventText.Text = DateTime.Now.ToString("HH:mm:ss") + "  " + app;
            lastEventText.ForeColor = Ink;
            DiagnosticLogStore.Add("info", "NOTIFICATION_DELIVERED");
            CaptureIfRequested();
        }

        private async Task RefreshServerStatusAsync()
        {
            if (!NetworkInterface.GetIsNetworkAvailable())
            {
                serverStatusCode = "offline";
                SetStatus("无网络连接", Red, "请检查这台电脑的网络");
                return;
            }

            bool authenticated = HasCredential();
            string bearer = authenticated
                ? state.ReceiverId + "." + StateStore.UnprotectSecret(state.ProtectedSecret)
                : null;
            foreach (string server in CandidateServers())
            {
                try
                {
                    await GetJsonAsync(BuildUrl(server,
                        authenticated ? "v1/device-status" : "v1/health"), bearer, 6);
                    state.ServerBase = server;
                    StateStore.Save(state);
                    credentialRecoveryRequired = false;
                    bool recovered = serverStatusCode != "online";
                    serverStatusCode = "online";
                    if (recovered) DiagnosticLogStore.Add("info", "SERVER_ONLINE");
                    SetStatus("服务器在线", Green, ServerLabel());
                    if (pairButton.Text == CredentialRecoveryButtonText)
                        pairButton.Text = "连接另一台手机";
                    if (authenticated) StartReceiver();
                    return;
                }
                catch (ApiException error)
                {
                    if (error.StatusCode == 401 || error.StatusCode == 403)
                    {
                        MarkAuthenticationFailed(error.StatusCode);
                        return;
                    }
                }
                catch { }
            }
            bool becameUnreachable = serverStatusCode != "unreachable";
            serverStatusCode = "unreachable";
            if (becameUnreachable) DiagnosticLogStore.Add("warning", "SERVER_UNREACHABLE");
            SetStatus("服务器不可用", Red, "稍后自动重试");
        }

        private async Task UploadDiagnosticsAsync()
        {
            diagnosticResult.Text = "";
            if (!HasCredential())
            {
                diagnosticResult.Text = "请先连接手机";
                return;
            }
            if (!NetworkInterface.GetIsNetworkAvailable())
            {
                diagnosticResult.Text = "无网络连接";
                return;
            }

            diagnosticButton.Enabled = false;
            diagnosticResult.Text = "正在安全上传";
            string bearer = state.ReceiverId + "." + StateStore.UnprotectSecret(state.ProtectedSecret);
            Dictionary<string, object> payload = new Dictionary<string, object>();
            payload["appVersion"] = "0.3.0";
            payload["platformVersion"] = Environment.OSVersion.VersionString;
            payload["networkStatus"] = "online";
            payload["serverStatus"] = serverStatusCode;
            payload["paired"] = true;
            payload["listenerEnabled"] = true;
            payload["backgroundRestricted"] = false;
            payload["entries"] = DiagnosticLogStore.Load();

            foreach (string server in CandidateServers())
            {
                try
                {
                    Dictionary<string, object> result = await PostJsonAsync(
                        BuildUrl(server, "v1/diagnostics"), payload, bearer, 8);
                    string diagnosticId = Value(result, "diagnosticId");
                    DiagnosticLogStore.Add("info", "DIAGNOSTIC_UPLOAD_OK", 201);
                    diagnosticResult.Text = "上传成功 · 编号 " + diagnosticId;
                    diagnosticResult.ForeColor = Green;
                    diagnosticButton.Enabled = true;
                    ShowConfirmation("诊断日志上传成功：" + diagnosticId);
                    return;
                }
                catch (ApiException error)
                {
                    if (error.StatusCode == 401 || error.StatusCode == 403)
                    {
                        diagnosticResult.Text = "需要重新连接";
                        diagnosticResult.ForeColor = Red;
                        diagnosticButton.Enabled = true;
                        return;
                    }
                    if (error.StatusCode == 429)
                    {
                        diagnosticResult.Text = "上传过于频繁，请稍后再试";
                        diagnosticResult.ForeColor = Red;
                        diagnosticButton.Enabled = true;
                        return;
                    }
                }
                catch { }
            }
            DiagnosticLogStore.Add("error", "DIAGNOSTIC_UPLOAD_FAILED");
            diagnosticResult.Text = "服务器不可用";
            diagnosticResult.ForeColor = Red;
            diagnosticButton.Enabled = true;
        }

        private void ShowTestNotification(bool capture)
        {
            Dictionary<string, object> sample = new Dictionary<string, object>();
            sample["id"] = Guid.NewGuid().ToString("N");
            sample["postTime"] = CurrentMilliseconds().ToString();
            sample["appName"] = "微信";
            sample["title"] = "系统通知测试";
            sample["text"] = "这是一条来自安卓转发的测试消息";
            sample["privacyMode"] = "full";
            if (capture)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(StateStore.CaptureFlagPath));
                File.WriteAllText(StateStore.CaptureFlagPath, "1");
            }
            Deliver(sample);
        }

        private void CaptureIfRequested()
        {
            if (!File.Exists(StateStore.CaptureFlagPath)) return;
            try { File.Delete(StateStore.CaptureFlagPath); }
            catch { }
            Task.Delay(1800).ContinueWith(delegate
            {
                try
                {
                    Rectangle bounds = Screen.PrimaryScreen.Bounds;
                    using (Bitmap bitmap = new Bitmap(bounds.Width, bounds.Height))
                    using (Graphics graphics = Graphics.FromImage(bitmap))
                    {
                        graphics.CopyFromScreen(bounds.Location, Point.Empty, bounds.Size);
                        bitmap.Save(StateStore.CapturePath, ImageFormat.Png);
                    }
                }
                catch { }
            });
        }

        private async Task<Dictionary<string, object>> PostJsonAsync(
            string url, Dictionary<string, object> body, string bearer, int timeoutSeconds)
        {
            using (HttpClient client = NewClient(bearer, timeoutSeconds))
            using (StringContent content = new StringContent(json.Serialize(body), Encoding.UTF8, "application/json"))
            using (HttpResponseMessage response = await client.PostAsync(url, content))
            {
                string raw = await response.Content.ReadAsStringAsync();
                Dictionary<string, object> result = ParseJson(raw);
                if (!response.IsSuccessStatusCode)
                    throw new ApiException((int)response.StatusCode,
                        FirstNonEmpty(Value(result, "error"), response.ReasonPhrase));
                return result;
            }
        }

        private async Task<Dictionary<string, object>> GetJsonAsync(
            string url, string bearer, int timeoutSeconds)
        {
            using (HttpClient client = NewClient(bearer, timeoutSeconds))
            using (HttpResponseMessage response = await client.GetAsync(url))
            {
                string raw = await response.Content.ReadAsStringAsync();
                Dictionary<string, object> result = ParseJson(raw);
                if (!response.IsSuccessStatusCode)
                    throw new ApiException((int)response.StatusCode,
                        FirstNonEmpty(Value(result, "error"), response.ReasonPhrase));
                return result;
            }
        }

        private Dictionary<string, object> ParseJson(string raw)
        {
            try
            {
                return json.Deserialize<Dictionary<string, object>>(raw)
                    ?? new Dictionary<string, object>();
            }
            catch { return new Dictionary<string, object>(); }
        }

        private static HttpClient NewClient(string bearer, int timeoutSeconds)
        {
            return NewClient(bearer, TimeSpan.FromSeconds(timeoutSeconds));
        }

        private static HttpClient NewClient(string bearer, TimeSpan timeout)
        {
            HttpClientHandler handler = new HttpClientHandler { AllowAutoRedirect = false };
            HttpClient client = new HttpClient(handler);
            client.Timeout = timeout;
            if (!String.IsNullOrEmpty(bearer))
                client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", bearer);
            return client;
        }

        private IEnumerable<string> CandidateServers()
        {
            return new string[] { OfficialServer };
        }

        private static string BuildUrl(string server, string route)
        {
            if (!String.Equals(server, OfficialServer, StringComparison.Ordinal))
                throw new InvalidOperationException("未授权的服务器地址");
            return OfficialServer + "/" + route.TrimStart('/');
        }

        private void SetStatus(string text, Color color, string detail)
        {
            statusText.Text = text;
            statusDot.ForeColor = color;
            detailText.Text = detail;
        }

        private void SetStatusThreadSafe(string text, Color color, string detail)
        {
            try { BeginInvoke((Action)delegate { SetStatus(text, color, detail); }); }
            catch { }
        }

        private void MarkAuthenticationFailed(int statusCode)
        {
            bool changed = serverStatusCode != "auth_failed";
            serverStatusCode = "auth_failed";
            credentialRecoveryRequired = true;
            if (changed) DiagnosticLogStore.Add("error", "AUTH_FAILED", statusCode);
            Action update = delegate
            {
                SetStatus("需要重新配对", Red, "设备凭据已失效");
                expiryText.Text = "服务器已拒绝本机凭据";
                pairButton.Text = CredentialRecoveryButtonText;
                pairButton.Enabled = true;
            };
            if (InvokeRequired)
            {
                try { BeginInvoke(update); }
                catch { }
            }
            else update();
        }

        private static string Value(Dictionary<string, object> values, string key)
        {
            if (values == null) return "";
            object value;
            return values.TryGetValue(key, out value) && value != null ? Convert.ToString(value) : "";
        }

        private static string FirstNonEmpty(params string[] values)
        {
            foreach (string value in values)
                if (!String.IsNullOrWhiteSpace(value)) return value.Trim();
            return "";
        }

        private static int PrivacyRank(string mode)
        {
            return mode == "full" ? 2 : mode == "title" ? 1 : 0;
        }

        private static int StatusCode(Exception error)
        {
            ApiException api = error as ApiException;
            return api == null ? 0 : api.StatusCode;
        }

        private Image DecodeQrPng(string base64)
        {
            try
            {
                byte[] bytes = Convert.FromBase64String(base64 ?? "");
                using (MemoryStream stream = new MemoryStream(bytes))
                using (Image image = Image.FromStream(stream))
                    return new Bitmap(image);
            }
            catch { return Icon.ToBitmap(); }
        }

        private void SetQrImage(Image image)
        {
            Image previous = qrBox.Image;
            qrBox.Image = image;
            if (previous != null) previous.Dispose();
        }

        private static string CleanRepeatedTitle(string title, string text)
        {
            title = (title ?? "").Trim();
            text = (text ?? "").Trim();
            if (title.Length == 0 || text.Length == 0) return text;
            Match match = Regex.Match(text, @"^(\[\d+条\])?\s*" + Regex.Escape(title) + @"\s*[:：]\s*");
            if (match.Success)
            {
                string count = match.Groups[1].Value;
                string remainder = text.Substring(match.Length).Trim();
                return (count + " " + remainder).Trim();
            }
            return text == title ? "" : text;
        }

        private static string TrimTo(string value, int length)
        {
            value = (value ?? "").Replace("\r", "").Trim();
            return value.Length <= length ? value : value.Substring(0, length - 1) + "…";
        }

        private static string FormatCode(string code)
        {
            if (String.IsNullOrEmpty(code) || code.Length != 6) return "------";
            return code.Substring(0, 3) + " " + code.Substring(3);
        }

        private static string ServerLabel()
        {
            return "官方 HTTPS · 安全连接";
        }

        private static string FriendlyError(Exception error)
        {
            if (error == null) return "稍后自动重试";
            string value = error.Message ?? error.GetType().Name;
            return TrimTo(value, 80);
        }

        private static long CurrentMilliseconds()
        {
            return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        private static Icon LoadAppIcon()
        {
            try
            {
                string path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "转发.ico");
                if (File.Exists(path)) return new Icon(path);
                return Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch { return SystemIcons.Application; }
        }

        private Label NewLabel(string text, float size, FontStyle style, Color color)
        {
            Label label = new Label();
            label.Text = text;
            label.Font = new Font("Microsoft YaHei UI", size, style, GraphicsUnit.Point);
            label.ForeColor = color;
            label.BackColor = Color.Transparent;
            label.AutoEllipsis = true;
            return label;
        }

        private static Panel NewPanel(Point location, Size size)
        {
            Panel panel = new Panel();
            panel.Location = location;
            panel.Size = size;
            panel.BackColor = Surface;
            panel.Paint += delegate(object sender, PaintEventArgs eventArgs)
            {
                using (Pen pen = new Pen(Color.FromArgb(218, 222, 228)))
                    eventArgs.Graphics.DrawRectangle(pen, 0, 0, panel.Width - 1, panel.Height - 1);
            };
            return panel;
        }

        private Button NewButton(string text, bool secondary)
        {
            Button button = new Button();
            button.Text = text;
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = secondary ? 1 : 0;
            button.FlatAppearance.BorderColor = Color.FromArgb(210, 214, 220);
            button.BackColor = secondary ? Surface : Ink;
            button.ForeColor = secondary ? Ink : Color.White;
            button.Font = new Font("Microsoft YaHei UI", 9.5F, FontStyle.Bold, GraphicsUnit.Point);
            button.Cursor = Cursors.Hand;
            return button;
        }
    }
}
