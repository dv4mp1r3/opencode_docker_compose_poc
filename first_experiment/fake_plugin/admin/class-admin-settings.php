<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Admin_Settings {
    public function register() {
        add_action('admin_init', [$this, 'register_settings']);
    }

    public function register_settings() {
        register_setting('fake_widget_group', Fake_Widget_Settings::OPTION_KEY);
    }
}
