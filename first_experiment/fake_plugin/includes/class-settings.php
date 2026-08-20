<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Settings {
    const OPTION_KEY = 'fake_widget_settings';

    public function get($key, $default = null) {
        $opts = get_option(self::OPTION_KEY, []);
        return $opts[$key] ?? $default;
    }

    public function set($key, $value) {
        $opts = get_option(self::OPTION_KEY, []);
        $opts[$key] = $value;
        update_option(self::OPTION_KEY, $opts);
    }
}
