<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Assets {
    public function register() {
        add_action('wp_enqueue_scripts', [$this, 'enqueue']);
    }

    public function enqueue() {
        wp_enqueue_style('fake-widget-css', FAKE_WIDGET_PLUGIN_URL . 'assets/css/widget.css');
        wp_enqueue_script('fake-widget-js', FAKE_WIDGET_PLUGIN_URL . 'assets/js/widget.js', [], '1.0.0', true);
    }
}
