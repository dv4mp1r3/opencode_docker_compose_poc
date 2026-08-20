<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_I18n {
    public function register() {
        add_action('init', [$this, 'load_textdomain']);
    }

    public function load_textdomain() {
        load_plugin_textdomain('fake-widget', false, dirname(plugin_basename(__FILE__)) . '/../languages');
    }
}
