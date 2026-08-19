package com.zundu.notifybridge;

final class ComponentAccess {
    private ComponentAccess() {}

    static boolean contains(String enabledComponents, String expectedComponent) {
        if (enabledComponents == null || expectedComponent == null
                || expectedComponent.length() == 0) return false;
        for (String value : enabledComponents.split(":")) {
            if (expectedComponent.equals(value.trim())) return true;
        }
        return false;
    }
}
