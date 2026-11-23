using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Shapes;
using Microsoft.Win32;

[assembly: AssemblyTitle("Resin 智能代理池网关 Windows 11 安装程序")]
[assembly: AssemblyProduct("Resin 智能代理池网关")]
[assembly: AssemblyCompany("Resin Project")]
[assembly: AssemblyVersion("1.2.0.0")]
[assembly: AssemblyFileVersion("1.2.0.0")]

namespace ResinWin11Installer
{
    public class SliceStream : Stream
    {
        private readonly Stream _inner;
        private readonly long _offset;
        private readonly long _length;
        private long _pos;

        public SliceStream(Stream inner, long offset, long length)
        {
            _inner = inner;
            _offset = offset;
            _length = length;
            _pos = 0;
            _inner.Position = _offset;
        }

        public override bool CanRead { get { return true; } }
        public override bool CanSeek { get { return true; } }
        public override bool CanWrite { get { return false; } }
        public override long Length { get { return _length; } }

        public override long Position
        {
            get { return _pos; }
            set { Seek(value, SeekOrigin.Begin); }
        }

        public override void Flush() { }

        public override int Read(byte[] buffer, int offset, int count)
        {
            long remaining = _length - _pos;
            if (remaining <= 0) return 0;
            if (count > remaining) count = (int)remaining;
            _inner.Position = _offset + _pos;
            int read = _inner.Read(buffer, offset, count);
            _pos += read;
            return read;
        }

        public override long Seek(long offset, SeekOrigin origin)
        {
            long next = _pos;
            if (origin == SeekOrigin.Begin) next = offset;
            else if (origin == SeekOrigin.Current) next = _pos + offset;
            else if (origin == SeekOrigin.End) next = _length + offset;
            if (next < 0) next = 0;
            if (next > _length) next = _length;
            _pos = next;
            _inner.Position = _offset + _pos;
            return _pos;
        }

        public override void SetLength(long value) { throw new NotSupportedException(); }
        public override void Write(byte[] buffer, int offset, int count) { throw new NotSupportedException(); }
    }

    public class Win11InstallerWindow : Window
    {
        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        private const string AppVersion = "1.2.0";
        private const string AppDisplayName = "Resin 智能代理池网关";
        private const string UninstallRegKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\Resin";
        private const string AutorunRegKey = @"Software\Microsoft\Windows\CurrentVersion\Run";

        private readonly bool _isUninstallMode;
        private TextBox _txtInstallDir;
        private CheckBox _chkDesktopIcon;
        private CheckBox _chkStartMenu;
        private CheckBox _chkAutorun;
        private CheckBox _chkLaunchAfter;

        private Grid _pageConfig;
        private Grid _pageProgress;
        private Grid _pageDone;

        private TextBlock _lblProgressStage;
        private TextBlock _lblProgressFile;
        private TextBlock _lblProgressPercent;
        private Border _progressBarFill;
        private double _progressBarMaxWidth = 580.0;

        public Win11InstallerWindow(bool isUninstallMode)
        {
            _isUninstallMode = isUninstallMode;
            Title = _isUninstallMode
                ? "卸载 Resin 智能代理池网关 v" + AppVersion
                : "Resin 智能代理池网关 v" + AppVersion + " — Windows 11 安装向导";
            Width = 660;
            Height = 470;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            WindowStyle = WindowStyle.None;
            AllowsTransparency = true;
            Background = Brushes.Transparent;
            ResizeMode = ResizeMode.NoResize;
            FontFamily = new FontFamily("Microsoft YaHei UI, Microsoft YaHei, Segoe UI");

            Loaded += OnWindowLoaded;
            Content = BuildRootShell();
        }

        private void OnWindowLoaded(object sender, RoutedEventArgs e)
        {
            try
            {
                IntPtr hwnd = new WindowInteropHelper(this).Handle;
                int dark = 1;
                DwmSetWindowAttribute(hwnd, 20, ref dark, sizeof(int));
                int round = 2; // DWMWCP_ROUND
                DwmSetWindowAttribute(hwnd, 33, ref round, sizeof(int));
            }
            catch { }
        }

        private static SolidColorBrush HexBrush(string hex)
        {
            return (SolidColorBrush)new BrushConverter().ConvertFromString(hex);
        }

        private UIElement BuildRootShell()
        {
            Border outer = new Border
            {
                CornerRadius = new CornerRadius(14),
                Background = HexBrush("#0B1120"),
                BorderBrush = HexBrush("#1E293B"),
                BorderThickness = new Thickness(1.5),
                Margin = new Thickness(8),
            };

            Grid mainGrid = new Grid();
            mainGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(44) });
            mainGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

            Border titleBar = new Border
            {
                Background = HexBrush("#0F172A"),
                CornerRadius = new CornerRadius(14, 14, 0, 0),
                BorderBrush = HexBrush("#1E293B"),
                BorderThickness = new Thickness(0, 0, 0, 1),
            };
            titleBar.MouseLeftButtonDown += (s, e) => { if (e.ButtonState == MouseButtonState.Pressed) DragMove(); };

            DockPanel titleDock = new DockPanel { LastChildFill = true, Margin = new Thickness(16, 0, 10, 0) };
            TextBlock titleText = new TextBlock
            {
                Text = _isUninstallMode
                    ? "🛡️ Resin 智能代理池网关 v" + AppVersion + " — 卸载管理向导"
                    : "🛡️ Resin 智能代理池网关 v" + AppVersion + " — Windows 11 现代安装器",
                Foreground = HexBrush("#38BDF8"),
                FontSize = 13.5,
                FontWeight = FontWeights.SemiBold,
                VerticalAlignment = VerticalAlignment.Center,
            };

            StackPanel winBtns = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
            DockPanel.SetDock(winBtns, Dock.Right);

            Button btnMin = CreateChromeButton("—", "#94A3B8", () => WindowState = WindowState.Minimized);
            Button btnClose = CreateChromeButton("✕", "#F87171", () => Close());
            winBtns.Children.Add(btnMin);
            winBtns.Children.Add(btnClose);

            titleDock.Children.Add(winBtns);
            titleDock.Children.Add(titleText);
            titleBar.Child = titleDock;
            Grid.SetRow(titleBar, 0);
            mainGrid.Children.Add(titleBar);

            Grid bodyContainer = new Grid { Margin = new Thickness(28, 20, 28, 22) };
            _pageConfig = BuildConfigPage();
            _pageProgress = BuildProgressPage();
            _pageDone = BuildDonePage();

            _pageProgress.Visibility = Visibility.Collapsed;
            _pageDone.Visibility = Visibility.Collapsed;

            bodyContainer.Children.Add(_pageConfig);
            bodyContainer.Children.Add(_pageProgress);
            bodyContainer.Children.Add(_pageDone);

            Grid.SetRow(bodyContainer, 1);
            mainGrid.Children.Add(bodyContainer);

            outer.Child = mainGrid;
            return outer;
        }

        private Button CreateChromeButton(string text, string fgHex, Action onClick)
        {
            Button btn = new Button
            {
                Content = text,
                Width = 34,
                Height = 28,
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                Foreground = HexBrush(fgHex),
                FontSize = 13,
                Cursor = Cursors.Hand,
                Margin = new Thickness(2, 0, 0, 0),
            };
            btn.Click += (s, e) => onClick();
            return btn;
        }

        private Grid BuildConfigPage()
        {
            Grid g = new Grid();
            StackPanel stack = new StackPanel();

            TextBlock heroTitle = new TextBlock
            {
                Text = _isUninstallMode
                    ? "确定要从电脑中卸载 Resin 智能代理池网关吗？"
                    : "欢迎安装 Resin 智能代理池网关 v" + AppVersion,
                Foreground = HexBrush("#F8FAFC"),
                FontSize = 22,
                FontWeight = FontWeights.Bold,
                Margin = new Thickness(0, 0, 0, 6),
            };
            stack.Children.Add(heroTitle);

            TextBlock heroSub = new TextBlock
            {
                Text = _isUninstallMode
                    ? "卸载程序将自动停止后台正在运行的网关进程、移除桌面与开始菜单快捷方式并清理系统注册表。"
                    : "将海量代理订阅转化为稳定、智能、可观测且支持粘性会话的高性能统一网关（内置 Go 核心与中文桌面控制台）。",
                Foreground = HexBrush("#94A3B8"),
                FontSize = 13,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 14),
            };
            stack.Children.Add(heroSub);

            if (!_isUninstallMode)
            {
                WrapPanel pills = new WrapPanel { Margin = new Thickness(0, 0, 0, 14) };
                pills.Children.Add(CreatePill("⚡ Go 1.26 高并发内核"));
                pills.Children.Add(CreatePill("🖥️ PySide6 原生中文界面"));
                pills.Children.Add(CreatePill("📈 实时吞吐折线监控"));
                pills.Children.Add(CreatePill("🤖 AI 自动巡检与大模型网关"));
                pills.Children.Add(CreatePill("📥 系统托盘常驻与开机自启"));
                stack.Children.Add(pills);

                Border dirCard = new Border
                {
                    Background = HexBrush("#1E293B"),
                    BorderBrush = HexBrush("#334155"),
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(10),
                    Padding = new Thickness(14, 12, 14, 12),
                    Margin = new Thickness(0, 0, 0, 14),
                };
                StackPanel dirStack = new StackPanel();
                dirStack.Children.Add(new TextBlock
                {
                    Text = "📂 安装位置 (支持自定义任意磁盘路径)",
                    Foreground = HexBrush("#38BDF8"),
                    FontSize = 12.5,
                    FontWeight = FontWeights.SemiBold,
                    Margin = new Thickness(0, 0, 0, 8),
                });

                DockPanel dirRow = new DockPanel { LastChildFill = true };
                Button btnBrowse = CreateActionButton("浏览文件夹...", "#334155", "#E2E8F0", 110, 34, OnBrowseFolder);
                DockPanel.SetDock(btnBrowse, Dock.Right);
                btnBrowse.Margin = new Thickness(8, 0, 0, 0);

                string defaultDir = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Programs",
                    "Resin"
                );
                _txtInstallDir = new TextBox
                {
                    Text = defaultDir,
                    Height = 34,
                    VerticalContentAlignment = VerticalAlignment.Center,
                    Background = HexBrush("#0F172A"),
                    Foreground = HexBrush("#F8FAFC"),
                    BorderBrush = HexBrush("#334155"),
                    BorderThickness = new Thickness(1),
                    Padding = new Thickness(10, 0, 10, 0),
                    FontSize = 13,
                };
                dirRow.Children.Add(btnBrowse);
                dirRow.Children.Add(_txtInstallDir);
                dirStack.Children.Add(dirRow);
                dirCard.Child = dirStack;
                stack.Children.Add(dirCard);

                Border optCard = new Border
                {
                    Background = HexBrush("#1E293B"),
                    BorderBrush = HexBrush("#334155"),
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(10),
                    Padding = new Thickness(14, 12, 14, 12),
                    Margin = new Thickness(0, 0, 0, 18),
                };
                UniformGrid optGrid = new UniformGrid { Columns = 2, Rows = 2 };
                _chkDesktopIcon = CreateModernCheckBox("创建桌面快捷方式", true);
                _chkStartMenu = CreateModernCheckBox("创建开始菜单程序快捷方式", true);
                _chkAutorun = CreateModernCheckBox("开机自动启动并驻留系统托盘", true);
                _chkLaunchAfter = CreateModernCheckBox("安装完成后立即启动 Resin", true);
                optGrid.Children.Add(_chkDesktopIcon);
                optGrid.Children.Add(_chkStartMenu);
                optGrid.Children.Add(_chkAutorun);
                optGrid.Children.Add(_chkLaunchAfter);
                optCard.Child = optGrid;
                stack.Children.Add(optCard);
            }

            DockPanel bottomBar = new DockPanel { LastChildFill = false };
            Button btnCancel = CreateActionButton("取消退出", "#334155", "#E2E8F0", 110, 42, () => Close());
            DockPanel.SetDock(btnCancel, Dock.Right);
            btnCancel.Margin = new Thickness(10, 0, 0, 0);

            Button btnPrimary = _isUninstallMode
                ? CreateActionButton("🗑️ 立即卸载 Resin", "#DC2626", "#FFFFFF", 210, 42, StartUninstallAsync)
                : CreateActionButton("⚡ 立即安装 Resin v" + AppVersion, "#0284C7", "#FFFFFF", 240, 42, StartInstallAsync);
            DockPanel.SetDock(btnPrimary, Dock.Right);

            bottomBar.Children.Add(btnCancel);
            bottomBar.Children.Add(btnPrimary);
            stack.Children.Add(bottomBar);

            g.Children.Add(stack);
            return g;
        }

        private Grid BuildProgressPage()
        {
            Grid g = new Grid();
            StackPanel stack = new StackPanel { VerticalAlignment = VerticalAlignment.Center };

            _lblProgressStage = new TextBlock
            {
                Text = "正在准备安装环境...",
                Foreground = HexBrush("#38BDF8"),
                FontSize = 20,
                FontWeight = FontWeights.Bold,
                Margin = new Thickness(0, 0, 0, 10),
            };
            stack.Children.Add(_lblProgressStage);

            _lblProgressPercent = new TextBlock
            {
                Text = "0%",
                Foreground = HexBrush("#10B981"),
                FontSize = 36,
                FontWeight = FontWeights.Bold,
                Margin = new Thickness(0, 0, 0, 14),
            };
            stack.Children.Add(_lblProgressPercent);

            Border track = new Border
            {
                Width = _progressBarMaxWidth,
                Height = 16,
                CornerRadius = new CornerRadius(8),
                Background = HexBrush("#1E293B"),
                BorderBrush = HexBrush("#334155"),
                BorderThickness = new Thickness(1),
                HorizontalAlignment = HorizontalAlignment.Left,
                Margin = new Thickness(0, 0, 0, 14),
            };

            LinearGradientBrush grad = new LinearGradientBrush(
                (Color)ColorConverter.ConvertFromString("#0284C7"),
                (Color)ColorConverter.ConvertFromString("#10B981"),
                0.0
            );
            _progressBarFill = new Border
            {
                Width = 0,
                Height = 14,
                CornerRadius = new CornerRadius(7),
                Background = grad,
                HorizontalAlignment = HorizontalAlignment.Left,
            };
            track.Child = _progressBarFill;
            stack.Children.Add(track);

            _lblProgressFile = new TextBlock
            {
                Text = "正在初始化高速多线程解压流...",
                Foreground = HexBrush("#94A3B8"),
                FontSize = 12.5,
                TextTrimming = TextTrimming.CharacterEllipsis,
            };
            stack.Children.Add(_lblProgressFile);

            g.Children.Add(stack);
            return g;
        }

        private Grid BuildDonePage()
        {
            Grid g = new Grid();
            StackPanel stack = new StackPanel { VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center };

            TextBlock badge = new TextBlock
            {
                Text = "✅",
                FontSize = 48,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 10),
            };
            stack.Children.Add(badge);

            TextBlock title = new TextBlock
            {
                Text = _isUninstallMode
                    ? "Resin 智能代理池网关已完成卸载"
                    : "Resin 智能代理池网关 v" + AppVersion + " 安装完成！",
                Foreground = HexBrush("#10B981"),
                FontSize = 22,
                FontWeight = FontWeights.Bold,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 10),
            };
            stack.Children.Add(title);

            TextBlock desc = new TextBlock
            {
                Text = _isUninstallMode
                    ? "所有快捷方式与程序组件均已清理完毕。"
                    : "桌面与开始菜单快捷方式已就绪，内置 Go 1.26 核心网关与 AI 自动巡检引擎随时待命。",
                Foreground = HexBrush("#94A3B8"),
                FontSize = 13.5,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 26),
            };
            stack.Children.Add(desc);

            Button btnFinish = CreateActionButton(
                _isUninstallMode ? "完成并关闭" : "🚀 完成并打开 Resin 智能代理池网关",
                "#059669",
                "#FFFFFF",
                280,
                44,
                OnFinishClicked
            );
            btnFinish.HorizontalAlignment = HorizontalAlignment.Center;
            stack.Children.Add(btnFinish);

            g.Children.Add(stack);
            return g;
        }

        private Border CreatePill(string text)
        {
            return new Border
            {
                Background = HexBrush("#162032"),
                BorderBrush = HexBrush("#0284C7"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(10, 4, 10, 4),
                Margin = new Thickness(0, 0, 8, 6),
                Child = new TextBlock
                {
                    Text = text,
                    Foreground = HexBrush("#E0F2FE"),
                    FontSize = 12,
                },
            };
        }

        private CheckBox CreateModernCheckBox(string label, bool isChecked)
        {
            return new CheckBox
            {
                Content = new TextBlock
                {
                    Text = label,
                    Foreground = HexBrush("#E2E8F0"),
                    FontSize = 13,
                    Margin = new Thickness(4, -1, 0, 0),
                },
                IsChecked = isChecked,
                Margin = new Thickness(0, 4, 12, 4),
                VerticalContentAlignment = VerticalAlignment.Center,
                Cursor = Cursors.Hand,
            };
        }

        private Button CreateActionButton(string text, string bgHex, string fgHex, double w, double h, Action onClick)
        {
            Button btn = new Button
            {
                Width = w,
                Height = h,
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                Cursor = Cursors.Hand,
            };
            Border b = new Border
            {
                Width = w,
                Height = h,
                CornerRadius = new CornerRadius(8),
                Background = HexBrush(bgHex),
                Child = new TextBlock
                {
                    Text = text,
                    Foreground = HexBrush(fgHex),
                    FontSize = 13.5,
                    FontWeight = FontWeights.Bold,
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center,
                },
            };
            btn.Content = b;
            btn.Click += (s, e) => onClick();
            return btn;
        }

        private void OnBrowseFolder()
        {
            OpenFileDialog dlg = new OpenFileDialog
            {
                Title = "选择 Resin 安装文件夹",
                CheckFileExists = false,
                CheckPathExists = true,
                ValidateNames = false,
                FileName = "选择此文件夹",
            };
            if (dlg.ShowDialog(this) == true)
            {
                string dir = System.IO.Path.GetDirectoryName(dlg.FileName);
                if (!string.IsNullOrEmpty(dir))
                {
                    if (!dir.EndsWith("Resin", StringComparison.OrdinalIgnoreCase))
                        dir = System.IO.Path.Combine(dir, "Resin");
                    _txtInstallDir.Text = dir;
                }
            }
        }

        private void UpdateProgressUI(int pct, string stage, string detail)
        {
            Dispatcher.Invoke(() =>
            {
                if (pct < 0) pct = 0;
                if (pct > 100) pct = 100;
                _lblProgressStage.Text = stage;
                _lblProgressPercent.Text = pct.ToString() + "%";
                _lblProgressFile.Text = detail;
                _progressBarFill.Width = _progressBarMaxWidth * (pct / 100.0);
            });
        }

        private async void StartInstallAsync()
        {
            string targetDir = _txtInstallDir.Text.Trim();
            if (string.IsNullOrEmpty(targetDir))
            {
                MessageBox.Show("请选择有效的安装路径。", "提示", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            bool createDesktop = _chkDesktopIcon.IsChecked == true;
            bool createStartMenu = _chkStartMenu.IsChecked == true;
            bool enableAutorun = _chkAutorun.IsChecked == true;

            _pageConfig.Visibility = Visibility.Collapsed;
            _pageProgress.Visibility = Visibility.Visible;

            try
            {
                await Task.Run(() => PerformInstallation(targetDir, createDesktop, createStartMenu, enableAutorun, UpdateProgressUI));
                _pageProgress.Visibility = Visibility.Collapsed;
                _pageDone.Visibility = Visibility.Visible;
            }
            catch (Exception ex)
            {
                MessageBox.Show("安装过程中发生错误: " + ex.Message, "安装错误", MessageBoxButton.OK, MessageBoxImage.Error);
                _pageProgress.Visibility = Visibility.Collapsed;
                _pageConfig.Visibility = Visibility.Visible;
            }
        }

        private async void StartUninstallAsync()
        {
            _pageConfig.Visibility = Visibility.Collapsed;
            _pageProgress.Visibility = Visibility.Visible;
            try
            {
                await Task.Run(() => PerformUninstall(UpdateProgressUI));
                _pageProgress.Visibility = Visibility.Collapsed;
                _pageDone.Visibility = Visibility.Visible;
            }
            catch (Exception ex)
            {
                MessageBox.Show("卸载遇到问题: " + ex.Message, "提示", MessageBoxButton.OK, MessageBoxImage.Warning);
                Close();
            }
        }

        private void OnFinishClicked()
        {
            if (!_isUninstallMode && (_chkLaunchAfter == null || _chkLaunchAfter.IsChecked == true))
            {
                try
                {
                    string exePath = System.IO.Path.Combine(_txtInstallDir.Text.Trim(), "Resin.exe");
                    if (File.Exists(exePath))
                    {
                        Process.Start(new ProcessStartInfo
                        {
                            FileName = exePath,
                            WorkingDirectory = _txtInstallDir.Text.Trim(),
                            UseShellExecute = true,
                        });
                    }
                }
                catch { }
            }
            Close();
        }

        public static void PerformInstallation(
            string targetDir,
            bool createDesktop,
            bool createStartMenu,
            bool enableAutorun,
            Action<int, string, string> progressCb
        )
        {
            progressCb(3, "正在停止运行中的旧版进程...", "检查 Resin.exe 与 resin-core.exe");
            StopRunningProcesses();

            Directory.CreateDirectory(targetDir);
            string selfPath = Process.GetCurrentProcess().MainModule.FileName;

            using (FileStream fs = new FileStream(selfPath, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (fs.Length < 24)
                    throw new InvalidDataException("安装包校验失败：文件长度异常。");

                fs.Seek(-24, SeekOrigin.End);
                byte[] footer = new byte[24];
                fs.Read(footer, 0, 24);
                long zipOffset = BitConverter.ToInt64(footer, 0);
                long zipLength = BitConverter.ToInt64(footer, 8);
                string magic = Encoding.ASCII.GetString(footer, 16, 8);

                if (magic != "RESINW11" || zipOffset <= 0 || zipLength <= 0 || zipOffset + zipLength + 24 > fs.Length)
                    throw new InvalidDataException("未找到内嵌的 Windows 11 安装载荷数据 (RESINW11)。");

                SliceStream slice = new SliceStream(fs, zipOffset, zipLength);
                using (ZipArchive archive = new ZipArchive(slice, ZipArchiveMode.Read))
                {
                    int total = Math.Max(1, archive.Entries.Count);
                    int idx = 0;
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        idx++;
                        string relPath = entry.FullName.Replace('/', '\\');
                        string destPath = System.IO.Path.Combine(targetDir, relPath);
                        if (string.IsNullOrEmpty(entry.Name))
                        {
                            Directory.CreateDirectory(destPath);
                            continue;
                        }
                        string parent = System.IO.Path.GetDirectoryName(destPath);
                        if (!string.IsNullOrEmpty(parent))
                            Directory.CreateDirectory(parent);

                        entry.ExtractToFile(destPath, true);
                        int pct = 5 + (int)(idx * 82.0 / total);
                        if (idx % 7 == 0 || idx == total)
                        {
                            progressCb(pct, "正在高速部署 Resin 核心组件...", string.Format("({0}/{1}) {2}", idx, total, entry.FullName));
                        }
                    }
                }
            }

            string mainExe = System.IO.Path.Combine(targetDir, "Resin.exe");
            string iconPath = System.IO.Path.Combine(targetDir, "assets", "resin.ico");
            if (!File.Exists(iconPath)) iconPath = mainExe;
            string uninstallExe = System.IO.Path.Combine(targetDir, "Uninstall-Resin.exe");

            progressCb(90, "正在创建快捷方式与系统菜单...", "配置 Windows 桌面与开始菜单快捷方式");
            if (createDesktop)
            {
                string desktopLnk = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                    AppDisplayName + ".lnk"
                );
                CreateShortcut(desktopLnk, mainExe, targetDir, iconPath, "启动 Resin 智能代理池网关");
            }
            if (createStartMenu)
            {
                string programsDir = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                    AppDisplayName
                );
                Directory.CreateDirectory(programsDir);
                CreateShortcut(
                    System.IO.Path.Combine(programsDir, AppDisplayName + ".lnk"),
                    mainExe,
                    targetDir,
                    iconPath,
                    "启动 Resin 智能代理池网关"
                );
                if (File.Exists(uninstallExe))
                {
                    CreateShortcut(
                        System.IO.Path.Combine(programsDir, "卸载 " + AppDisplayName + ".lnk"),
                        uninstallExe,
                        targetDir,
                        iconPath,
                        "卸载 Resin 智能代理池网关"
                    );
                }
            }

            progressCb(96, "正在写入 Windows 11 应用注册表...", "注册应用卸载信息与开机自启配置");
            RegisterWindows11App(targetDir, mainExe, iconPath, uninstallExe, enableAutorun);
            progressCb(100, "安装完成！", "Resin 智能代理池网关 v" + AppVersion + " 已准备就绪");
        }

        private static void PerformUninstall(Action<int, string, string> progressCb)
        {
            progressCb(15, "正在停止 Resin 后台进程...", "终止 Resin.exe 与 resin-core.exe");
            StopRunningProcesses();

            progressCb(45, "正在移除桌面与开始菜单快捷方式...", "清理快捷方式图标");
            try
            {
                string desktopLnk = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                    AppDisplayName + ".lnk"
                );
                if (File.Exists(desktopLnk)) File.Delete(desktopLnk);

                string programsDir = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                    AppDisplayName
                );
                if (Directory.Exists(programsDir)) Directory.Delete(programsDir, true);
            }
            catch { }

            progressCb(75, "正在清理 Windows 注册表项...", "移除应用登记与开机自启项");
            try
            {
                Registry.CurrentUser.DeleteSubKeyTree(UninstallRegKey, false);
                using (RegistryKey runKey = Registry.CurrentUser.OpenSubKey(AutorunRegKey, true))
                {
                    if (runKey != null) runKey.DeleteValue("ResinProxyGateway", false);
                }
            }
            catch { }

            progressCb(100, "卸载已完成！", "已清理所有快捷方式与注册表项");
        }

        private static void StopRunningProcesses()
        {
            foreach (string name in new[] { "Resin", "resin-core" })
            {
                try
                {
                    foreach (Process p in Process.GetProcessesByName(name))
                    {
                        if (p.Id == Process.GetCurrentProcess().Id) continue;
                        p.Kill();
                        p.WaitForExit(3000);
                    }
                }
                catch { }
            }
        }

        private static void CreateShortcut(string lnkPath, string targetExe, string workDir, string iconPath, string description)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return;
                object shell = Activator.CreateInstance(shellType);
                object shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { lnkPath });
                Type scType = shortcut.GetType();
                scType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { targetExe });
                scType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { workDir });
                scType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { iconPath });
                scType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { description });
                scType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
            }
            catch { }
        }

        private static void RegisterWindows11App(string targetDir, string mainExe, string iconPath, string uninstallExe, bool enableAutorun)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallRegKey))
                {
                    if (key != null)
                    {
                        key.SetValue("DisplayName", AppDisplayName);
                        key.SetValue("DisplayVersion", AppVersion);
                        key.SetValue("Publisher", "Resin Project (Chinese Edition)");
                        key.SetValue("DisplayIcon", iconPath);
                        key.SetValue("InstallLocation", targetDir);
                        key.SetValue("UninstallString", "\"" + uninstallExe + "\" --uninstall");
                        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                        key.SetValue("EstimatedSize", 145000, RegistryValueKind.DWord);
                    }
                }
                using (RegistryKey runKey = Registry.CurrentUser.OpenSubKey(AutorunRegKey, true))
                {
                    if (runKey != null)
                    {
                        if (enableAutorun)
                            runKey.SetValue("ResinProxyGateway", "\"" + mainExe + "\" --minimized");
                        else
                            runKey.DeleteValue("ResinProxyGateway", false);
                    }
                }
            }
            catch { }
        }

        [STAThread]
        public static int Main(string[] args)
        {
            try { SetProcessDPIAware(); } catch { }

            bool silent = false;
            bool uninstall = false;
            string customDir = System.IO.Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs",
                "Resin"
            );

            string exeName = System.IO.Path.GetFileName(Process.GetCurrentProcess().MainModule.FileName);
            if (exeName.StartsWith("Uninstall", StringComparison.OrdinalIgnoreCase))
                uninstall = true;

            foreach (string arg in args)
            {
                if (arg.Equals("/S", StringComparison.OrdinalIgnoreCase) ||
                    arg.Equals("/SILENT", StringComparison.OrdinalIgnoreCase) ||
                    arg.Equals("/VERYSILENT", StringComparison.OrdinalIgnoreCase))
                {
                    silent = true;
                }
                else if (arg.Equals("--uninstall", StringComparison.OrdinalIgnoreCase) ||
                         arg.Equals("/UNINSTALL", StringComparison.OrdinalIgnoreCase))
                {
                    uninstall = true;
                }
                else if (arg.StartsWith("/DIR=", StringComparison.OrdinalIgnoreCase))
                {
                    customDir = arg.Substring(5).Trim('"');
                }
            }

            if (silent && !uninstall)
            {
                try
                {
                    PerformInstallation(customDir, true, true, true, (p, s, d) => { });
                    return 0;
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine("Silent install failed: " + ex.Message);
                    return 1;
                }
            }

            Application app = new Application();
            app.Run(new Win11InstallerWindow(uninstall));
            return 0;
        }
    }
}
