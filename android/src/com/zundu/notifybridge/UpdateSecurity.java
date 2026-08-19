package com.zundu.notifybridge;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.time.Instant;
import java.util.Arrays;
import java.util.Base64;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

final class UpdateSecurity {
    static final String MANIFEST_URL =
            "https://updates.example.com/downloads/forwarder/test/android.json";
    static final String KEY_ID = "8545bd8392ab5de2";
    static final long MAX_PACKAGE_BYTES = 100L * 1024L * 1024L;
    static final int MAX_MANIFEST_BYTES = 64 * 1024;

    private static final String HOST = "updates.example.com";
    private static final String DOWNLOAD_PREFIX = "/downloads/forwarder/test/";
    private static final String PUBLIC_KEY_BASE64 =
            "MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAvtEyLwpBwuLl3beIHljcyva1LI9BStCnW7ml3XZllEHsTRU2DJ/gb8D6ElvocBr0BjKxtgMJAb/RQoh7AL+U8EZ+QTooT6DZC7tMxxu4C0J9Mg9UFAIA8WVdXEOsSoqjeXYanMYZDiZ21SrklCl5mIYsL5f6wOnSBd+Oy18yUiaCX87YirxkfBH3ooNEDXAT61tc9ieNBFo4Wr4/2yeB7DC+xFAzKBNMwQBzRqEwNkD/w0kUh/k0zs0VDz35RwNoI46XzC6e8UUVwKbNg6GO/9dvtpgyZDEqP1Ldr3T3c3hHLDKmiaklYexO9P43vO1exff2EBt4oTU0NBdUZvyvkFhZQjGWDqAycpdgdzVCRJcCFHBVBvEHWeTCXbaJyBLAv41SJ4a92iiwj3+1qw5yaVIWw9e8aGBVXTu7G8cMU6r5/XN/UF+u449fVneVCMQZ+wDfwrc0h29IY+y+RzMHQrz9yHkv1YiFmL/00K/c4Bpgu0TeurMI33M/W3u1bTJ/AgMBAAE=";
    private static final Set<String> FIELDS = new HashSet<>(Arrays.asList(
            "schema", "channel", "platform", "versionCode", "version", "url",
            "sha256", "size", "publishedAt", "notes", "keyId", "signature"));

    private UpdateSecurity() {}

    static ManifestData validateAndVerify(Map<String, Object> values, long currentVersionCode)
            throws Exception {
        return validateAndVerify(values, currentVersionCode, PUBLIC_KEY_BASE64, KEY_ID);
    }

    static ManifestData validateAndVerify(
            Map<String, Object> values,
            long currentVersionCode,
            String publicKeyBase64,
            String expectedKeyId) throws Exception {
        if (values == null || !FIELDS.equals(values.keySet())) {
            throw new SecurityException("更新清单字段不正确");
        }
        long schema = integer(values, "schema");
        String channel = string(values, "channel", 16);
        String platform = string(values, "platform", 16);
        long versionCode = integer(values, "versionCode");
        String version = string(values, "version", 40);
        String url = string(values, "url", 512);
        String sha256 = string(values, "sha256", 64);
        long size = integer(values, "size");
        String publishedAt = string(values, "publishedAt", 64);
        String notes = string(values, "notes", 1024);
        String keyId = string(values, "keyId", 32);
        String signatureText = string(values, "signature", 1024);

        if (schema != 1 || !"test".equals(channel) || !"android".equals(platform)
                || !expectedKeyId.equals(keyId)) {
            throw new SecurityException("更新清单身份不正确");
        }
        if (versionCode <= currentVersionCode) {
            throw new SecurityException("没有更高版本");
        }
        if (!version.matches("[0-9]+(?:\\.[0-9]+){1,3}(?:-[A-Za-z0-9.]+)?")) {
            throw new SecurityException("版本格式不正确");
        }
        if (!sha256.matches("[0-9a-f]{64}")) {
            throw new SecurityException("文件摘要格式不正确");
        }
        if (size <= 0 || size > MAX_PACKAGE_BYTES) {
            throw new SecurityException("更新文件大小不正确");
        }
        Instant.parse(publishedAt);
        validateDownloadUrl(url, version);

        ManifestData data = new ManifestData(
                schema, channel, platform, versionCode, version, url, sha256, size,
                publishedAt, notes, keyId, signatureText);
        byte[] signatureBytes;
        try {
            signatureBytes = Base64.getDecoder().decode(signatureText);
        } catch (IllegalArgumentException invalidBase64) {
            throw new SecurityException("更新签名格式不正确");
        }
        boolean verified;
        try {
            Signature verifier = Signature.getInstance("SHA256withRSA");
            verifier.initVerify(publicKey(publicKeyBase64));
            verifier.update(data.canonical().getBytes(StandardCharsets.UTF_8));
            verified = verifier.verify(signatureBytes);
        } catch (Exception invalidSignature) {
            throw new SecurityException("更新签名校验失败");
        }
        if (!verified) {
            throw new SecurityException("更新签名校验失败");
        }
        return data;
    }

    static void validateDownloadUrl(String value, String version) throws Exception {
        URI uri = new URI(value);
        String expectedPath = DOWNLOAD_PREFIX + "forwarder-android-" + version + "-test.apk";
        if (!"https".equals(uri.getScheme())
                || !HOST.equals(uri.getHost())
                || uri.getPort() != -1
                || !expectedPath.equals(uri.getRawPath())
                || uri.getRawQuery() != null
                || uri.getRawFragment() != null
                || uri.getRawUserInfo() != null) {
            throw new SecurityException("更新下载地址不受信任");
        }
    }

    private static PublicKey publicKey(String encodedKey) throws Exception {
        byte[] encoded = Base64.getDecoder().decode(encodedKey);
        return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(encoded));
    }

    private static String string(Map<String, Object> values, String key, int maxLength) {
        Object value = values.get(key);
        if (!(value instanceof String)) throw new SecurityException("更新清单字段类型不正确");
        String text = (String) value;
        if (text.length() > maxLength || text.indexOf('\n') >= 0 || text.indexOf('\r') >= 0) {
            throw new SecurityException("更新清单字段内容不正确");
        }
        return text;
    }

    private static long integer(Map<String, Object> values, String key) {
        Object value = values.get(key);
        if (!(value instanceof Number)) throw new SecurityException("更新清单字段类型不正确");
        Number number = (Number) value;
        long result = number.longValue();
        if (number.doubleValue() != (double) result || result < 0) {
            throw new SecurityException("更新清单数字不正确");
        }
        return result;
    }

    static final class ManifestData {
        final long schema;
        final String channel;
        final String platform;
        final long versionCode;
        final String version;
        final String url;
        final String sha256;
        final long size;
        final String publishedAt;
        final String notes;
        final String keyId;
        final String signature;

        ManifestData(
                long schema, String channel, String platform, long versionCode, String version,
                String url, String sha256, long size, String publishedAt, String notes,
                String keyId, String signature) {
            this.schema = schema;
            this.channel = channel;
            this.platform = platform;
            this.versionCode = versionCode;
            this.version = version;
            this.url = url;
            this.sha256 = sha256;
            this.size = size;
            this.publishedAt = publishedAt;
            this.notes = notes;
            this.keyId = keyId;
            this.signature = signature;
        }

        String canonical() {
            return schema + "\n" + channel + "\n" + platform + "\n" + versionCode + "\n"
                    + version + "\n" + url + "\n" + sha256 + "\n" + size + "\n"
                    + publishedAt + "\n" + notes + "\n" + keyId;
        }
    }
}
