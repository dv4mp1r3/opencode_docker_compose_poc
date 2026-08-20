<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Public {
    public function register() {
        add_action('wp_footer', [$this, 'maybe_render_footer_widget']);
    }

    public function maybe_render_footer_widget() {
        if (!is_active_widget(false, false, 'fake_widget_footer')) {
            return;
        }
        include FAKE_WIDGET_PLUGIN_DIR . 'public/partials/widget-display.php';
    }
}
