<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Admin_Page {
    public function register() {
        add_action('admin_menu', [$this, 'add_menu']);
    }

    public function add_menu() {
        add_options_page(
            'Fake Widget',
            'Fake Widget',
            'manage_options',
            'fake-widget-settings',
            [$this, 'render_page']
        );
    }

    public function render_page() {
        include FAKE_WIDGET_PLUGIN_DIR . 'admin/partials/admin-display.php';
    }
}
