package com.zundu.notifybridge;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class SecretStore {
    static final String KEY_CIPHERTEXT = "device_secret_ciphertext";
    static final String KEY_IV = "device_secret_iv";
    static final String KEY_FORMAT = "device_secret_format";

    private static final String KEYSTORE = "AndroidKeyStore";
    private static final String KEY_ALIAS = "com.zundu.notifybridge.device-secret.v1";
    private static final String FORMAT_V1 = "aes-gcm-v1";

    private SecretStore() {}

    static String read(Context context, SharedPreferences preferences, String legacyKey) {
        return readSlot(context, preferences, legacyKey, "sender");
    }

    static String readSlot(
            Context context, SharedPreferences preferences, String legacyKey, String slot) {
        String ciphertextKey = storageKey(KEY_CIPHERTEXT, slot);
        String ivKey = storageKey(KEY_IV, slot);
        String formatKey = storageKey(KEY_FORMAT, slot);
        boolean hasEncrypted = preferences.contains(ciphertextKey)
                || preferences.contains(ivKey)
                || preferences.contains(formatKey);
        if (hasEncrypted) {
            if (preferences.contains(legacyKey)) {
                preferences.edit().remove(legacyKey).commit();
            }
            try {
                if (!FORMAT_V1.equals(preferences.getString(formatKey, ""))) return "";
                byte[] iv = Base64.decode(preferences.getString(ivKey, ""), Base64.NO_WRAP);
                byte[] ciphertext = Base64.decode(
                        preferences.getString(ciphertextKey, ""), Base64.NO_WRAP);
                if (iv.length != 12 || ciphertext.length < 17) return "";
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                String alias = keyAlias(slot);
                cipher.init(Cipher.DECRYPT_MODE, key(false, alias), new GCMParameterSpec(128, iv));
                cipher.updateAAD(aad(context, alias));
                return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
            } catch (Exception ignored) {
                return "";
            }
        }

        String legacy = preferences.getString(legacyKey, "");
        if (legacy.isEmpty()) return "";
        try {
            SharedPreferences.Editor editor = preferences.edit();
            stageWriteSlot(context, editor, legacy, legacyKey, slot);
            if (!editor.commit()) return "";
            return legacy;
        } catch (Exception ignored) {
            return "";
        }
    }

    static void stageWrite(
            Context context,
            SharedPreferences.Editor editor,
            String secret,
            String legacyKey) throws Exception {
        stageWriteSlot(context, editor, secret, legacyKey, "sender");
    }

    static void stageWriteSlot(
            Context context,
            SharedPreferences.Editor editor,
            String secret,
            String legacyKey,
            String slot) throws Exception {
        if (secret == null || secret.isEmpty()) {
            throw new IllegalArgumentException("empty device credential");
        }
        String alias = keyAlias(slot);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key(true, alias));
        cipher.updateAAD(aad(context, alias));
        byte[] ciphertext = cipher.doFinal(secret.getBytes(StandardCharsets.UTF_8));
        byte[] iv = cipher.getIV();
        if (iv == null || iv.length != 12) throw new IllegalStateException("invalid GCM IV");
        editor.putString(storageKey(KEY_FORMAT, slot), FORMAT_V1)
                .putString(storageKey(KEY_IV, slot), Base64.encodeToString(iv, Base64.NO_WRAP))
                .putString(storageKey(KEY_CIPHERTEXT, slot), Base64.encodeToString(ciphertext, Base64.NO_WRAP))
                .remove(legacyKey);
    }

    static void stageClear(SharedPreferences.Editor editor, String legacyKey) {
        stageClearSlot(editor, legacyKey, "sender");
    }

    static void stageClearSlot(
            SharedPreferences.Editor editor, String legacyKey, String slot) {
        editor.remove(storageKey(KEY_CIPHERTEXT, slot))
                .remove(storageKey(KEY_IV, slot))
                .remove(storageKey(KEY_FORMAT, slot))
                .remove(legacyKey);
    }

    static void deleteKey() {
        deleteKeySlot("sender");
    }

    static void deleteKeySlot(String slot) {
        try {
            KeyStore store = KeyStore.getInstance(KEYSTORE);
            store.load(null);
            String alias = keyAlias(slot);
            if (store.containsAlias(alias)) store.deleteEntry(alias);
        } catch (Exception ignored) {
            // Stored ciphertext is already removed. Never recreate or expose plaintext here.
        }
    }

    private static SecretKey key(boolean create, String alias) throws Exception {
        KeyStore store = KeyStore.getInstance(KEYSTORE);
        store.load(null);
        java.security.Key existing = store.getKey(alias, null);
        if (existing instanceof SecretKey) return (SecretKey) existing;
        if (!create) throw new IllegalStateException("device credential key unavailable");

        KeyGenerator generator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, KEYSTORE);
        generator.init(new KeyGenParameterSpec.Builder(
                alias,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setRandomizedEncryptionRequired(true)
                .build());
        return generator.generateKey();
    }

    private static String storageKey(String base, String slot) {
        return "sender".equals(slot) ? base : base + "_" + slot;
    }

    private static String keyAlias(String slot) {
        return "sender".equals(slot) ? KEY_ALIAS : KEY_ALIAS + "." + slot;
    }

    private static byte[] aad(Context context, String alias) {
        return (context.getPackageName() + "\n" + alias).getBytes(StandardCharsets.UTF_8);
    }
}
