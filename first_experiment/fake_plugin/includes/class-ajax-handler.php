<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Ajax_Handler {
    public function register() {
        add_action('wp_ajax_fake_widget_refresh', [$this, 'handle_refresh']);
        add_action('wp_ajax_nopriv_fake_widget_refresh', [$this, 'handle_refresh']);
    }

    public function handle_refresh() {
        check_ajax_referer('fake_widget_nonce', 'nonce');
        $renderer = new Fake_Widget_Renderer();
        wp_send_json_success(['html' => $renderer->render(['mode' => 'default', 'limit' => 5])]);
    }
}
