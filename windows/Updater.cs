using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace XXZF.Forwarder
{
    internal static class WindowsFileSecurity
    {
        private static readonly string PrivateRoot = Path.GetFullPath(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "XXZF"));

        internal static void EnsurePrivateDirectory(string path)
        {
            string fullPath = RequirePrivatePath(path, true);
            string relative = fullPath.Length == PrivateRoot.Length
                ? "" : fullPath.Substring(PrivateRoot.Length + 1);
            string current = PrivateRoot;
            RejectReparsePointIfPresent(current);
            if (!Directory.Exists(current)) Directory.CreateDirectory(current);
            RejectReparsePointIfPresent(current);
            ApplyDirectoryAcl(current);
            if (relative.Length == 0) return;

            foreach (string part in relative.Split(Path.DirectorySeparatorChar))
            {
                if (part.Length == 0) continue;
                current = Path.Combine(current, part);
                RejectReparsePointIfPresent(current);
                if (!Directory.Exists(current)) Directory.CreateDirectory(current);
                RejectReparsePointIfPresent(current);
                ApplyDirectoryAcl(current);
            }
        }

        internal static void ProtectFile(string path)
        {
            string fullPath = RequirePrivatePath(path, false);
            FileInfo file = new FileInfo(fullPath);
            if (!file.Exists) throw new FileNotFoundException("需要保护的文件不存在", fullPath);
            if ((file.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("安全文件不能是链接或重解析点");

            FileSecurity security = new FileSecurity();
            security.SetAccessRuleProtection(true, false);
            SecurityIdentifier user = WindowsIdentity.GetCurrent().User;
            if (user == null) throw new InvalidOperationException("无法取得当前用户标识");
            SecurityIdentifier system = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
            security.SetOwner(user);
            security.AddAccessRule(new FileSystemAccessRule(
                user, FileSystemRights.FullControl, AccessControlType.Allow));
            security.AddAccessRule(new FileSystemAccessRule(
                system, FileSystemRights.FullControl, AccessControlType.Allow));
            file.SetAccessControl(security);
        }

        internal static void RejectReparsePointIfPresent(string path)
        {
            if (!Directory.Exists(path) && !File.Exists(path)) return;
            FileAttributes attributes = File.GetAttributes(path);
            if ((attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("路径不能是链接或重解析点");
        }

        private static string RequirePrivatePath(string path, bool directory)
        {
            if (String.IsNullOrWhiteSpace(path)) throw new InvalidOperationException("安全路径为空");
            string fullPath = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar);
            string prefix = PrivateRoot + Path.DirectorySeparatorChar;
            if (!String.Equals(fullPath, PrivateRoot, StringComparison.OrdinalIgnoreCase)
                && !fullPath.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("路径不在应用私有目录");
            if (!directory && String.Equals(fullPath, PrivateRoot, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("文件路径无效");
            return fullPath;
        }

        private static void ApplyDirectoryAcl(string path)
        {
            DirectorySecurity security = new DirectorySecurity();
            security.SetAccessRuleProtection(true, false);
            InheritanceFlags inheritance = InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit;
            SecurityIdentifier user = WindowsIdentity.GetCurrent().User;
            if (user == null) throw new InvalidOperationException("无法取得当前用户标识");
            SecurityIdentifier system = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
            security.SetOwner(user);
            security.AddAccessRule(new FileSystemAccessRule(
                user, FileSystemRights.FullControl, inheritance,
                PropagationFlags.None, AccessControlType.Allow));
            security.AddAccessRule(new FileSystemAccessRule(
                system, FileSystemRights.FullControl, inheritance,
                PropagationFlags.None, AccessControlType.Allow));
            new DirectoryInfo(path).SetAccessControl(security);
        }
    }

    internal sealed class UpdateManifest
    {
        internal int VersionCode { get; set; }
        internal string Version { get; set; }
        internal Uri PackageUri { get; set; }
        internal string Sha256 { get; set; }
        internal long Size { get; set; }
        internal string Notes { get; set; }
    }

    internal enum UpdateCheckKind
    {
        Current,
        Available,
        Failed
    }

    internal sealed class UpdateCheckResult
    {
        internal UpdateCheckKind Kind { get; set; }
        internal UpdateManifest Manifest { get; set; }
        internal string Message { get; set; }
    }

    internal sealed class UpdateManager
    {
        internal const int CurrentVersionCode = 3;
        internal const string CurrentVersion = "0.3.0";

        private const string ManifestUrl =
            "https://updates.example.com/downloads/forwarder/test/windows.json";
        private const string PackageBasePath = "/downloads/forwarder/test/";
        private const string OfficialHost = "updates.example.com";
        private const string ExpectedKeyId = "8545bd8392ab5de2";
        private const int MaximumManifestBytes = 64 * 1024;
        private const long MinimumPackageBytes = 32 * 1024;
        private const long MaximumPackageBytes = 128L * 1024L * 1024L;
        private const string PublicExponentHex = "010001";
        private const string PublicModulusHex =
            "BED1322F0A41C2E2E5DDB7881E58DCCAF6B52C8F414AD0A75BB9A5DD76659441EC4D15360C9FE06FC0FA125BE8701AF40632B1B6030901BFD142887B00BF94F0467E413A284FA0D90BBB4CC71BB80B427D320F54140200F1655D5C43AC4A8AA379761A9CC6190E2676D52AE494297998862C2F97FAC0E9D205DF8ECB5F325226825FCED88ABC647C11F7A283440D7013EB5B5CF6278D045A385ABE3FDB2781EC30BEC4503328134CC1007346A1303640FFC3491487F934CECD150F3DF9470368238E97CC2E9EF14515C0A6CD83A18EFFD76FB6983264312A3F52DDAF74F77378472C32A689A92561EC4EF4FE37BCED5EC5F7F6101B78A1353434175466FCAF9058594231960EA03272976077354244970214705506F10759E4C25DB689C812C0BF8D522786BDDA28B08F7FB5AB0E72695216C3D7BC6860555D3BBB1BC70C53AAF9FD737F505FAEE38F5F56779508C419FB00DFC2B734876F4863ECBE47330742BCFDC8792FD5888598BFF4D0AFDCE01A60BB44DEBAB308DF733F5B7BB56D327F";

        private static readonly string[] CanonicalFields = new string[] {
            "schema", "channel", "platform", "versionCode", "version", "url",
            "sha256", "size", "publishedAt", "notes", "keyId"
        };
        private static readonly HashSet<string> AllowedFields = new HashSet<string>(
            new string[] {
                "schema", "channel", "platform", "versionCode", "version", "url",
                "sha256", "size", "publishedAt", "notes", "keyId", "signature"
            }, StringComparer.Ordinal);
        private static readonly Regex VersionPattern = new Regex(
            @"^[0-9]+\.[0-9]+\.[0-9]+$", RegexOptions.CultureInvariant);
        private static readonly Regex HashPattern = new Regex(
            @"^[a-f0-9]{64}$", RegexOptions.CultureInvariant);
        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer {
            MaxJsonLength = MaximumManifestBytes,
            RecursionLimit = 8
        };

        private readonly string updateDirectory;
        private readonly string installerPath;

        internal UpdateManager()
        {
            updateDirectory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "XXZF", "updates");
            installerPath = Path.Combine(updateDirectory, "forwarder-windows-update.exe");
        }

        internal async Task<UpdateCheckResult> CheckAsync(CancellationToken cancellationToken)
        {
            try
            {
                byte[] body = await DownloadSmallFileAsync(
                    new Uri(ManifestUrl), MaximumManifestBytes, cancellationToken).ConfigureAwait(false);
                UpdateManifest manifest = ParseAndVerifyManifest(
                    Encoding.UTF8.GetString(body), true);
                if (manifest.VersionCode <= CurrentVersionCode)
                {
                    return new UpdateCheckResult {
                        Kind = UpdateCheckKind.Current,
                        Message = "已是最新版本 " + CurrentVersion
                    };
                }
                return new UpdateCheckResult {
                    Kind = UpdateCheckKind.Available,
                    Manifest = manifest,
                    Message = "发现新版本 " + manifest.Version
                };
            }
            catch (OperationCanceledException)
            {
                if (cancellationToken.IsCancellationRequested) throw;
                return new UpdateCheckResult {
                    Kind = UpdateCheckKind.Failed,
                    Message = "检查更新超时"
                };
            }
            catch (Exception error)
            {
                return new UpdateCheckResult {
                    Kind = UpdateCheckKind.Failed,
                    Message = SafeError(error)
                };
            }
        }

        internal async Task<string> DownloadAndLaunchAsync(
            UpdateManifest manifest, Action<int> progress, CancellationToken cancellationToken)
        {
            if (manifest == null) throw new ArgumentNullException("manifest");
            if (manifest.VersionCode <= CurrentVersionCode)
                throw new InvalidDataException("拒绝同版本或降级安装");
            EnsureSafeUpdateDirectory();
            string partialPath = installerPath + ".part";
            WindowsFileSecurity.RejectReparsePointIfPresent(partialPath);
            WindowsFileSecurity.RejectReparsePointIfPresent(installerPath);
            DeleteFileQuietly(partialPath);
            DeleteFileQuietly(installerPath);

            try
            {
                using (HttpClient client = NewHttpClient(TimeSpan.FromMinutes(8)))
                using (HttpResponseMessage response = await client.GetAsync(
                    manifest.PackageUri, HttpCompletionOption.ResponseHeadersRead,
                    cancellationToken).ConfigureAwait(false))
                {
                    RejectRedirect(response);
                    if (response.StatusCode != HttpStatusCode.OK)
                        throw new InvalidDataException("安装包下载失败：HTTP " + (int)response.StatusCode);
                    if (response.Content.Headers.ContentLength.HasValue
                        && response.Content.Headers.ContentLength.Value != manifest.Size)
                        throw new InvalidDataException("安装包响应大小不符");

                    using (Stream input = await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                    using (FileStream output = new FileStream(
                        partialPath, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                        81920, FileOptions.SequentialScan))
                    using (SHA256 sha = SHA256.Create())
                    {
                        byte[] buffer = new byte[81920];
                        long total = 0;
                        int read;
                        while ((read = await input.ReadAsync(
                            buffer, 0, buffer.Length, cancellationToken).ConfigureAwait(false)) > 0)
                        {
                            total += read;
                            if (total > manifest.Size || total > MaximumPackageBytes)
                                throw new InvalidDataException("安装包超过允许大小");
                            await output.WriteAsync(
                                buffer, 0, read, cancellationToken).ConfigureAwait(false);
                            sha.TransformBlock(buffer, 0, read, null, 0);
                            if (progress != null)
                                progress((int)Math.Min(100, total * 100L / manifest.Size));
                        }
                        sha.TransformFinalBlock(new byte[0], 0, 0);
                        output.Flush(true);
                        if (total != manifest.Size)
                            throw new InvalidDataException("安装包实际大小不符");
                        string actualHash = BytesToHex(sha.Hash);
                        if (!FixedTimeEquals(actualHash, manifest.Sha256))
                            throw new CryptographicException("安装包 SHA-256 校验失败");
                    }
                }

                WindowsFileSecurity.ProtectFile(partialPath);
                File.Move(partialPath, installerPath);
                VerifyDownloadedInstaller(installerPath, manifest);
                ApplyInternetZoneMarker(installerPath, manifest.PackageUri);

                ProcessStartInfo start = new ProcessStartInfo {
                    FileName = installerPath,
                    Arguments = "/Q",
                    WorkingDirectory = updateDirectory,
                    UseShellExecute = true
                };
                Process process = Process.Start(start);
                if (process == null) throw new InvalidOperationException("无法启动更新安装程序");
                return installerPath;
            }
            catch
            {
                DeleteFileQuietly(partialPath);
                DeleteFileQuietly(installerPath);
                throw;
            }
        }

        internal static UpdateManifest ParseAndVerifyManifest(string raw)
        {
            return ParseAndVerifyManifest(raw, false);
        }

        private static UpdateManifest ParseAndVerifyManifest(string raw, bool allowCurrent)
        {
            if (String.IsNullOrWhiteSpace(raw) || Encoding.UTF8.GetByteCount(raw) > MaximumManifestBytes)
                throw new InvalidDataException("更新清单为空或过大");

            Dictionary<string, object> values;
            try { values = Json.Deserialize<Dictionary<string, object>>(raw); }
            catch (Exception error) { throw new InvalidDataException("更新清单不是有效 JSON", error); }
            if (values == null || values.Count != AllowedFields.Count)
                throw new InvalidDataException("更新清单字段数量无效");
            foreach (string key in values.Keys)
                if (!AllowedFields.Contains(key)) throw new InvalidDataException("更新清单包含未知字段");
            foreach (string key in AllowedFields)
                if (!values.ContainsKey(key)) throw new InvalidDataException("更新清单缺少字段 " + key);

            long schema = StrictInteger(values, "schema");
            long versionCode = StrictInteger(values, "versionCode");
            long size = StrictInteger(values, "size");
            string channel = StrictString(values, "channel", 16);
            string platform = StrictString(values, "platform", 16);
            string version = StrictString(values, "version", 32);
            string url = StrictString(values, "url", 512);
            string sha256 = StrictString(values, "sha256", 64).ToLowerInvariant();
            string publishedAt = StrictString(values, "publishedAt", 64);
            string notes = StrictString(values, "notes", 1024);
            string keyId = StrictString(values, "keyId", 64);
            string signatureText = StrictString(values, "signature", 2048);

            if (schema != 1 || channel != "test" || platform != "windows")
                throw new InvalidDataException("更新清单协议或平台不匹配");
            if (versionCode < 1 || versionCode > Int32.MaxValue
                || (!allowCurrent && versionCode <= CurrentVersionCode))
                throw new InvalidDataException("拒绝同版本或降级更新");
            if (!VersionPattern.IsMatch(version)) throw new InvalidDataException("版本号格式无效");
            if (versionCode == CurrentVersionCode && version != CurrentVersion)
                throw new InvalidDataException("当前版本号与版本代码不一致");
            if (!HashPattern.IsMatch(sha256)) throw new InvalidDataException("SHA-256 格式无效");
            if (size < MinimumPackageBytes || size > MaximumPackageBytes)
                throw new InvalidDataException("安装包大小超出限制");
            if (keyId != ExpectedKeyId) throw new CryptographicException("更新签名密钥不匹配");
            if (ContainsNewline(notes)) throw new InvalidDataException("更新说明包含非法换行");

            DateTimeOffset published;
            if (!DateTimeOffset.TryParseExact(
                publishedAt, "yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out published))
                throw new InvalidDataException("发布时间格式无效");
            if (published > DateTimeOffset.UtcNow.AddMinutes(10))
                throw new InvalidDataException("发布时间超出允许范围");

            Uri packageUri;
            if (!Uri.TryCreate(url, UriKind.Absolute, out packageUri))
                throw new InvalidDataException("安装包地址无效");
            ValidatePackageUri(packageUri, version);

            string canonical = BuildCanonical(values);
            byte[] signature;
            try { signature = Convert.FromBase64String(signatureText); }
            catch (FormatException error) { throw new CryptographicException("更新签名格式无效", error); }
            if (signature.Length != 384) throw new CryptographicException("更新签名长度无效");
            VerifySignature(canonical, signature);

            return new UpdateManifest {
                VersionCode = (int)versionCode,
                Version = version,
                PackageUri = packageUri,
                Sha256 = sha256,
                Size = size,
                Notes = notes
            };
        }

        private static async Task<byte[]> DownloadSmallFileAsync(
            Uri uri, int maximumBytes, CancellationToken cancellationToken)
        {
            ValidateManifestUri(uri);
            using (HttpClient client = NewHttpClient(TimeSpan.FromSeconds(15)))
            using (HttpResponseMessage response = await client.GetAsync(
                uri, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false))
            {
                RejectRedirect(response);
                if (response.StatusCode != HttpStatusCode.OK)
                    throw new InvalidDataException("更新服务响应 HTTP " + (int)response.StatusCode);
                if (response.Content.Headers.ContentLength.HasValue
                    && response.Content.Headers.ContentLength.Value > maximumBytes)
                    throw new InvalidDataException("更新清单超过大小限制");
                using (Stream input = await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                using (MemoryStream output = new MemoryStream())
                {
                    byte[] buffer = new byte[4096];
                    int read;
                    while ((read = await input.ReadAsync(
                        buffer, 0, buffer.Length, cancellationToken).ConfigureAwait(false)) > 0)
                    {
                        if (output.Length + read > maximumBytes)
                            throw new InvalidDataException("更新清单超过大小限制");
                        output.Write(buffer, 0, read);
                    }
                    return output.ToArray();
                }
            }
        }

        private static HttpClient NewHttpClient(TimeSpan timeout)
        {
            HttpClientHandler handler = new HttpClientHandler {
                AllowAutoRedirect = false,
                AutomaticDecompression = DecompressionMethods.None,
                UseCookies = false
            };
            HttpClient client = new HttpClient(handler);
            client.Timeout = timeout;
            client.DefaultRequestHeaders.UserAgent.ParseAdd("XXZF-Forwarder-Windows/" + CurrentVersion);
            return client;
        }

        private static void RejectRedirect(HttpResponseMessage response)
        {
            int status = (int)response.StatusCode;
            if (status >= 300 && status <= 399)
                throw new InvalidDataException("更新服务重定向已被拒绝");
        }

        private static void ValidateManifestUri(Uri uri)
        {
            if (uri == null || uri.Scheme != Uri.UriSchemeHttps
                || !String.Equals(uri.IdnHost, OfficialHost, StringComparison.OrdinalIgnoreCase)
                || uri.Port != 443 || uri.AbsolutePath != "/downloads/forwarder/test/windows.json"
                || !String.IsNullOrEmpty(uri.Query) || !String.IsNullOrEmpty(uri.Fragment)
                || !String.IsNullOrEmpty(uri.UserInfo))
                throw new InvalidDataException("更新清单地址不在允许范围");
        }

        private static void ValidatePackageUri(Uri uri, string version)
        {
            string expectedPath = PackageBasePath + "forwarder-windows-" + version + "-test.exe";
            if (uri.Scheme != Uri.UriSchemeHttps
                || !String.Equals(uri.IdnHost, OfficialHost, StringComparison.OrdinalIgnoreCase)
                || uri.Port != 443 || uri.AbsolutePath != expectedPath
                || !String.IsNullOrEmpty(uri.Query) || !String.IsNullOrEmpty(uri.Fragment)
                || !String.IsNullOrEmpty(uri.UserInfo))
                throw new InvalidDataException("安装包地址不在允许范围");
        }

        private static string BuildCanonical(Dictionary<string, object> values)
        {
            StringBuilder canonical = new StringBuilder();
            for (int index = 0; index < CanonicalFields.Length; index++)
            {
                string key = CanonicalFields[index];
                string value = key == "schema" || key == "versionCode" || key == "size"
                    ? StrictInteger(values, key).ToString(CultureInfo.InvariantCulture)
                    : StrictString(values, key, key == "notes" ? 1024 : 512);
                if (ContainsNewline(value)) throw new InvalidDataException("规范字段包含非法换行");
                if (index > 0) canonical.Append('\n');
                canonical.Append(value);
            }
            return canonical.ToString();
        }

        private static void VerifySignature(string canonical, byte[] signature)
        {
            RSAParameters parameters = new RSAParameters {
                Modulus = HexToBytes(PublicModulusHex),
                Exponent = HexToBytes(PublicExponentHex)
            };
            using (RSACryptoServiceProvider rsa = new RSACryptoServiceProvider(3072))
            {
                rsa.PersistKeyInCsp = false;
                rsa.ImportParameters(parameters);
                if (!rsa.VerifyData(
                    Encoding.UTF8.GetBytes(canonical), new SHA256CryptoServiceProvider(), signature))
                    throw new CryptographicException("更新清单签名校验失败");
            }
        }

        private void EnsureSafeUpdateDirectory()
        {
            string expected = Path.GetFullPath(Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "XXZF", "updates"));
            if (!String.Equals(Path.GetFullPath(updateDirectory), expected, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("更新目录无效");
            WindowsFileSecurity.EnsurePrivateDirectory(updateDirectory);
        }

        private static void VerifyDownloadedInstaller(string path, UpdateManifest manifest)
        {
            FileInfo file = new FileInfo(path);
            if (!file.Exists || file.Length != manifest.Size
                || (file.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("下载的安装包文件无效");
            WindowsFileSecurity.ProtectFile(path);
            using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (SHA256 sha = SHA256.Create())
            {
                string actualHash = BytesToHex(sha.ComputeHash(stream));
                if (!FixedTimeEquals(actualHash, manifest.Sha256))
                    throw new CryptographicException("启动前安装包校验失败");
            }
        }

        private static void ApplyInternetZoneMarker(string path, Uri source)
        {
            string marker = "[ZoneTransfer]\r\nZoneId=3\r\nHostUrl="
                + source.AbsoluteUri + "\r\n";
            try
            {
                File.WriteAllText(path + ":Zone.Identifier", marker, Encoding.ASCII);
            }
            catch (Exception error)
            {
                throw new IOException("无法交由 Windows SmartScreen 检查安装包", error);
            }
        }

        private static string StrictString(Dictionary<string, object> values, string key, int maximumLength)
        {
            object raw;
            if (!values.TryGetValue(key, out raw) || !(raw is string))
                throw new InvalidDataException("字段 " + key + " 类型无效");
            string value = (string)raw;
            if (value.Length == 0 || value.Length > maximumLength || value.IndexOf('\0') >= 0)
                throw new InvalidDataException("字段 " + key + " 长度无效");
            return value;
        }

        private static long StrictInteger(Dictionary<string, object> values, string key)
        {
            object raw;
            if (!values.TryGetValue(key, out raw) || raw == null
                || (!(raw is int) && !(raw is long)))
                throw new InvalidDataException("字段 " + key + " 类型无效");
            return Convert.ToInt64(raw, CultureInfo.InvariantCulture);
        }

        private static bool ContainsNewline(string value)
        {
            return value.IndexOf('\r') >= 0 || value.IndexOf('\n') >= 0;
        }

        private static byte[] HexToBytes(string value)
        {
            if (value == null || value.Length == 0 || value.Length % 2 != 0)
                throw new FormatException("无效十六进制数据");
            byte[] result = new byte[value.Length / 2];
            for (int index = 0; index < result.Length; index++)
                result[index] = Byte.Parse(value.Substring(index * 2, 2), NumberStyles.HexNumber);
            return result;
        }

        private static string BytesToHex(byte[] value)
        {
            StringBuilder result = new StringBuilder(value.Length * 2);
            foreach (byte item in value) result.Append(item.ToString("x2", CultureInfo.InvariantCulture));
            return result.ToString();
        }

        private static bool FixedTimeEquals(string left, string right)
        {
            if (left == null || right == null || left.Length != right.Length) return false;
            int difference = 0;
            for (int index = 0; index < left.Length; index++) difference |= left[index] ^ right[index];
            return difference == 0;
        }

        private static string SafeError(Exception error)
        {
            if (error is HttpRequestException) return "无法连接更新服务";
            if (error is TaskCanceledException) return "检查更新超时";
            if (error is CryptographicException) return "更新安全校验失败";
            if (error is InvalidDataException) return error.Message;
            return "检查更新失败";
        }

        private static void DeleteFileQuietly(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); }
            catch { }
        }
    }
}
