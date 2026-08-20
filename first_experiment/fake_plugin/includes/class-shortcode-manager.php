<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Shortcode_Manager {
    public function register() {
        add_shortcode('fake_widget', [$this, 'render']);
    }

    public function render($atts) {
        $atts = shortcode_atts([
            'mode' => 'default',
            'limit' => 5,
        ], $atts, 'fake_widget');

        $renderer = new Fake_Widget_Renderer();
        return $renderer->render($atts);
    }
}
