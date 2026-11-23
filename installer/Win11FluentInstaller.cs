// Resin 智能代理池网关 v1.3.2 — 原生 Windows 11 Fluent Dark 全中文高分屏自适应安装器与卸载器
// 采用硬件加速 .NET WPF + Win11 DWM 原生暗色圆角窗口 + 自适应 ScrollViewer 与底部固定按钮栏，完美兼容 100%~300% DPI 缩放与各种屏幕分辨率

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
using Microsoft.Win32;

[assembly: AssemblyTitle("Resin 智能代理池网关 Windows 11 安装程序")]
[assembly: AssemblyProduct("Resin 智能代理池网关")]
[assembly: AssemblyCompany("Resin Project")]
[assembly: AssemblyVersion("1.3.2.0")]
[assembly: AssemblyFileVersion("1.3.2.0")]

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

        private const string AppVersion = "1.3.2";
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
        private ColumnDefinition _colProgressFill;
        private ColumnDefinition _colProgressRemain;

        public Win11InstallerWindow(bool isUninstallMode)
        {
            _isUninstallMode = isUninstallMode;
            Title = _isUninstallMode
                ? "卸载 Resin 智能代理池网关 v" + AppVersion
                : "Resin 智能代理池网关 v" + AppVersion + " — Windows 11 安装向导";

            Rect workArea = SystemParameters.WorkArea;
            double targetW = Math.Min(740.0, Math.Max(560.0, workArea.Width * 0.90));
            double maxH = Math.Max(460.0, workArea.Height * 0.92);

            Width = targetW;
            MinWidth = Math.Min(580.0, workArea.Width * 0.85);
            MinHeight = Math.Min(460.0, maxH);
            MaxWidth = workArea.Width * 0.96;
            MaxHeight = maxH;

            // 自动根据实际 DPI 与字体高度适配窗口高度，同时受 MaxHeight 安全边界约束，永不超出屏幕
            SizeToContent = SizeToContent.Height;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            WindowStyle = WindowStyle.SingleBorderWindow;
            ResizeMode = ResizeMode.CanResize;
            UseLayoutRounding = true;
            SnapsToDevicePixels = true;
            TextOptions.SetTextFormattingMode(this, TextFormattingMode.Display);
            TextOptions.SetTextRenderingMode(this, TextRenderingMode.ClearType);

            Background = HexBrush("#0B1120");
            Foreground = HexBrush("#F8FAFC");
            FontFamily = new FontFamily("Microsoft YaHei UI, Microsoft YaHei, Segoe UI");

            Loaded += OnWindowLoaded;
            ContentRendered += OnWindowContentRendered;
            Content = BuildRootShell();
        }

        private void OnWindowLoaded(object sender, RoutedEventArgs e)
        {
            try
            {
                IntPtr hwnd = new WindowInteropHelper(this).Handle;
                int dark = 1;
                DwmSetWindowAttribute(hwnd, 20, ref dark, sizeof(int)); // DWMWA_USE_IMMERSIVE_DARK_MODE
                DwmSetWindowAttribute(hwnd, 19, ref dark, sizeof(int)); // DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1
                int round = 2;
                DwmSetWindowAttribute(hwnd, 33, ref round, sizeof(int)); // DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
                int captionColor = 0x002A170F; // COLORREF BGR for #0F172A
                DwmSetWindowAttribute(hwnd, 35, ref captionColor, sizeof(int)); // DWMWA_CAPTION_COLOR
            }
            catch { }
        }

        private void OnWindowContentRendered(object sender, EventArgs e)
        {
            // 内容渲染完成后切换为 Manual 以便用户可自由拖拽调整大小，并精确居中于工作区
            Rect workArea = SystemParameters.WorkArea;
            double actualH = Math.Min(ActualHeight, workArea.Height * 0.92);
            double actualW = Math.Min(ActualWidth, workArea.Width * 0.95);
            SizeToContent = SizeToContent.Manual;
            Width = actualW;
            Height = Math.Max(MinHeight, actualH);
            Left = workArea.Left + Math.Max(0, (workArea.Width - Width) / 2.0);
            Top = workArea.Top + Math.Max(0, (workArea.Height - Height) / 2.0);
        }

        private static SolidColorBrush HexBrush(string hex)
        {
            return (SolidColorBrush)new BrushConverter().ConvertFromString(hex);
        }

        private UIElement BuildRootShell()
        {
            Grid mainGrid = new Grid
            {
                Background = HexBrush("#0B1120"),
            };
            mainGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            mainGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

            // 1. 顶部品牌横幅栏
            Border headerBanner = new Border
            {
                Background = HexBrush("#0F172A"),
                BorderBrush = HexBrush("#1E293B"),
                BorderThickness = new Thickness(0, 0, 0, 1),
                Padding = new Thickness(24, 14, 24, 14),
            };

            DockPanel headerDock = new DockPanel { LastChildFill = true };
            Border versionBadge = new Border
            {
                Background = HexBrush("#0284C7"),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(10, 4, 10, 4),
                VerticalAlignment = VerticalAlignment.Center,
                Child = new TextBlock
                {
                    Text = "v" + AppVersion + " Win11 64位正式版",
                    Foreground = Brushes.White,
                    FontSize = 12,
                    FontWeight = FontWeights.Bold,
                },
            };
            DockPanel.SetDock(versionBadge, Dock.Right);

            StackPanel titleStack = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            titleStack.Children.Add(new TextBlock
            {
                Text = _isUninstallMode
                    ? "🛡️ Resin 智能代理池网关 — 卸载向导"
                    : "🛡️ Resin 智能代理池网关 — Windows 11 安装向导",
                Foreground = HexBrush("#38BDF8"),
                FontSize = 18,
                FontWeight = FontWeights.Bold,
                TextWrapping = TextWrapping.Wrap,
            });
            titleStack.Children.Add(new TextBlock
            {
                Text = _isUninstallMode
                    ? "安全停止后台网关服务、清理快捷方式与系统注册表项"
                    : "将海量代理订阅转化为稳定、智能、可观测且支持粘性会话的高性能统一网关",
                Foreground = HexBrush("#94A3B8"),
                FontSize = 12.5,
                Margin = new Thickness(0, 4, 12, 0),
                TextWrapping = TextWrapping.Wrap,
            });

            headerDock.Children.Add(versionBadge);
            headerDock.Children.Add(titleStack);
            headerBanner.Child = headerDock;
            Grid.SetRow(headerBanner, 0);
            mainGrid.Children.Add(headerBanner);

            // 2. 主体内容区
            Grid bodyContainer = new Grid { Margin = new Thickness(24, 16, 24, 18) };
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

            return mainGrid;
        }

        private Grid BuildConfigPage()
        {
            // 采用 3 行 Grid 架构：Row 0 顶部特性区 (Auto)，Row 1 中部自适应滚动区 (*)，Row 2 底部固定按钮栏 (Auto)
            // 确保在任何分辨率与系统文字缩放 (100%~300%) 下底部「立即安装」按钮永远固定可见、绝不裁剪
            Grid pageGrid = new Grid();
            pageGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            pageGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            pageGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            if (!_isUninstallMode)
            {
                WrapPanel pills = new WrapPanel { Margin = new Thickness(0, 0, 0, 12) };
                pills.Children.Add(CreatePill("⚡ Go 1.26 高并发内核"));
                pills.Children.Add(CreatePill("🖥️ PySide6 原生中文界面"));
                pills.Children.Add(CreatePill("📈 实时吞吐折线监控"));
                pills.Children.Add(CreatePill("🤖 AI 自动巡检与大模型网关"));
                pills.Children.Add(CreatePill("📥 系统托盘常驻与开机自启"));
                Grid.SetRow(pills, 0);
                pageGrid.Children.Add(pills);
            }
            else
            {
                Border warnCard = new Border
                {
                    Background = HexBrush("#1E293B"),
                    BorderBrush = HexBrush("#EF4444"),
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(10),
                    Padding = new Thickness(16, 14, 16, 14),
                    Margin = new Thickness(0, 0, 0, 12),
                    Child = new TextBlock
                    {
                        Text = "您即将从电脑中卸载 Resin 智能代理池网关。卸载过程会自动停止正在运行的网关守护进程，并移除桌面快捷方式、开始菜单入口与系统注册表信息。",
                        Foreground = HexBrush("#F8FAFC"),
                        FontSize = 13.5,
                        TextWrapping = TextWrapping.Wrap,
                        LineHeight = 22,
                    },
                };
                Grid.SetRow(warnCard, 0);
                pageGrid.Children.Add(warnCard);
            }

            // 中部滚动容器
            ScrollViewer scroll = new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                Padding = new Thickness(0, 0, 4, 0),
            };

            StackPanel midStack = new StackPanel();
            if (!_isUninstallMode)
            {
                // 安装目录选择卡片
                Border dirCard = new Border
                {
                    Background = HexBrush("#1E293B"),
                    BorderBrush = HexBrush("#334155"),
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(10),
                    Padding = new Thickness(16, 12, 16, 14),
                    Margin = new Thickness(0, 0, 0, 12),
                };
                StackPanel dirStack = new StackPanel();
                dirStack.Children.Add(new TextBlock
                {
                    Text = "📂 安装位置 (支持自定义任意磁盘路径，免管理员权限即可极速部署)",
                    Foreground = HexBrush("#38BDF8"),
                    FontSize = 13,
                    FontWeight = FontWeights.SemiBold,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 0, 0, 8),
                });

                Grid dirRow = new Grid();
                dirRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                dirRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

                string defaultDir = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Programs",
                    "Resin"
                );
                _txtInstallDir = new TextBox
                {
                    Text = defaultDir,
                    MinHeight = 36,
                    VerticalContentAlignment = VerticalAlignment.Center,
                    Background = HexBrush("#0F172A"),
                    Foreground = HexBrush("#F8FAFC"),
                    BorderBrush = HexBrush("#334155"),
                    BorderThickness = new Thickness(1),
                    Padding = new Thickness(10, 6, 10, 6),
                    FontSize = 13,
                };
                Grid.SetColumn(_txtInstallDir, 0);

                Button btnBrowse = CreateActionButton("浏览文件夹...", "#334155", "#E2E8F0", 118, 36, OnBrowseFolder);
                btnBrowse.Margin = new Thickness(10, 0, 0, 0);
                Grid.SetColumn(btnBrowse, 1);

                dirRow.Children.Add(_txtInstallDir);
                dirRow.Children.Add(btnBrowse);
                dirStack.Children.Add(dirRow);
                dirCard.Child = dirStack;
                midStack.Children.Add(dirCard);

                // 安装选项卡片
                Border optCard = new Border
                {
                    Background = HexBrush("#1E293B"),
                    BorderBrush = HexBrush("#334155"),
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(10),
                    Padding = new Thickness(16, 12, 16, 14),
                    Margin = new Thickness(0, 0, 0, 8),
                };
                StackPanel optStack = new StackPanel();
                optStack.Children.Add(new TextBlock
                {
                    Text = "⚙️ 快捷方式与启动选项",
                    Foreground = HexBrush("#38BDF8"),
                    FontSize = 13,
                    FontWeight = FontWeights.SemiBold,
                    Margin = new Thickness(0, 0, 0, 8),
                });

                Grid optGrid = new Grid();
                optGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                optGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                optGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                optGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

                _chkDesktopIcon = CreateModernCheckBox("创建桌面快捷方式", true);
                _chkStartMenu = CreateModernCheckBox("创建开始菜单程序快捷方式", true);
                _chkAutorun = CreateModernCheckBox("开机自动启动并驻留系统托盘", true);
                _chkLaunchAfter = CreateModernCheckBox("安装完成后立即启动 Resin", true);

                Grid.SetRow(_chkDesktopIcon, 0); Grid.SetColumn(_chkDesktopIcon, 0);
                Grid.SetRow(_chkStartMenu, 0); Grid.SetColumn(_chkStartMenu, 1);
                Grid.SetRow(_chkAutorun, 1); Grid.SetColumn(_chkAutorun, 0);
                Grid.SetRow(_chkLaunchAfter, 1); Grid.SetColumn(_chkLaunchAfter, 1);

                optGrid.Children.Add(_chkDesktopIcon);
                optGrid.Children.Add(_chkStartMenu);
                optGrid.Children.Add(_chkAutorun);
                optGrid.Children.Add(_chkLaunchAfter);

                optStack.Children.Add(optGrid);
                optCard.Child = optStack;
                midStack.Children.Add(optCard);
            }

            scroll.Content = midStack;
            Grid.SetRow(scroll, 1);
            pageGrid.Children.Add(scroll);

            // Row 2: 底部固定操作按钮栏
            Border bottomBorder = new Border
            {
                BorderBrush = HexBrush("#1E293B"),
                BorderThickness = new Thickness(0, 1, 0, 0),
                Padding = new Thickness(0, 14, 0, 0),
                Margin = new Thickness(0, 8, 0, 0),
            };
            DockPanel bottomBar = new DockPanel { LastChildFill = false };

            TextBlock tipLeft = new TextBlock
            {
                Text = _isUninstallMode ? "感谢您使用 Resin 智能代理池网关" : "内置 Go 核心引擎 + PySide6 原生中文控制台",
                Foreground = HexBrush("#64748B"),
                FontSize = 12,
                VerticalAlignment = VerticalAlignment.Center,
            };
            DockPanel.SetDock(tipLeft, Dock.Left);

            Button btnCancel = CreateActionButton("取消退出", "#334155", "#E2E8F0", 110, 42, () => Close());
            DockPanel.SetDock(btnCancel, Dock.Right);
            btnCancel.Margin = new Thickness(10, 0, 0, 0);

            Button btnPrimary = _isUninstallMode
                ? CreateActionButton("🗑️ 立即卸载 Resin", "#DC2626", "#FFFFFF", 210, 42, StartUninstallAsync)
                : CreateActionButton("⚡ 立即安装 Resin v" + AppVersion, "#0284C7", "#FFFFFF", 240, 42, StartInstallAsync);
            DockPanel.SetDock(btnPrimary, Dock.Right);

            bottomBar.Children.Add(tipLeft);
            bottomBar.Children.Add(btnCancel);
            bottomBar.Children.Add(btnPrimary);
            bottomBorder.Child = bottomBar;

            Grid.SetRow(bottomBorder, 2);
            pageGrid.Children.Add(bottomBorder);

            return pageGrid;
        }

        private Grid BuildProgressPage()
        {
            Grid g = new Grid { VerticalAlignment = VerticalAlignment.Center };
            StackPanel stack = new StackPanel { VerticalAlignment = VerticalAlignment.Center };

            _lblProgressStage = new TextBlock
            {
                Text = "正在准备安装环境...",
                Foreground = HexBrush("#38BDF8"),
                FontSize = 20,
                FontWeight = FontWeights.Bold,
                TextWrapping = TextWrapping.Wrap,
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

            // 自适应比例宽度进度条，无论窗口宽度如何变化都 100% 贴合
            Border track = new Border
            {
                Height = 18,
                CornerRadius = new CornerRadius(9),
                Background = HexBrush("#1E293B"),
                BorderBrush = HexBrush("#334155"),
                BorderThickness = new Thickness(1),
                HorizontalAlignment = HorizontalAlignment.Stretch,
                Margin = new Thickness(0, 0, 0, 14),
            };

            Grid progGrid = new Grid();
            _colProgressFill = new ColumnDefinition { Width = new GridLength(0, GridUnitType.Star) };
            _colProgressRemain = new ColumnDefinition { Width = new GridLength(100, GridUnitType.Star) };
            progGrid.ColumnDefinitions.Add(_colProgressFill);
            progGrid.ColumnDefinitions.Add(_colProgressRemain);

            LinearGradientBrush grad = new LinearGradientBrush(
                (Color)ColorConverter.ConvertFromString("#0284C7"),
                (Color)ColorConverter.ConvertFromString("#10B981"),
                0.0
            );
            Border fillBorder = new Border
            {
                CornerRadius = new CornerRadius(8),
                Background = grad,
            };
            Grid.SetColumn(fillBorder, 0);
            progGrid.Children.Add(fillBorder);
            track.Child = progGrid;
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
            StackPanel stack = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Center,
            };

            TextBlock badge = new TextBlock
            {
                Text = "✅",
                FontSize = 46,
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
                TextWrapping = TextWrapping.Wrap,
                TextAlignment = TextAlignment.Center,
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
                TextWrapping = TextWrapping.Wrap,
                TextAlignment = TextAlignment.Center,
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
                Padding = new Thickness(10, 5, 10, 5),
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
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(6, -1, 8, 0),
                },
                IsChecked = isChecked,
                Margin = new Thickness(0, 6, 8, 6),
                VerticalContentAlignment = VerticalAlignment.Center,
                Cursor = Cursors.Hand,
            };
        }

        private Button CreateActionButton(string text, string bgHex, string fgHex, double w, double h, Action onClick)
        {
            Button btn = new Button
            {
                MinWidth = w,
                MinHeight = h,
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                Cursor = Cursors.Hand,
            };
            Border b = new Border
            {
                MinWidth = w,
                MinHeight = h,
                Padding = new Thickness(14, 6, 14, 6),
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
                _colProgressFill.Width = new GridLength(pct, GridUnitType.Star);
                _colProgressRemain.Width = new GridLength(Math.Max(0, 100 - pct), GridUnitType.Star);
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
