<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Cache {
    public function get($key) {
        return get_transient($key);
    }

    public function set($key, $value, $ttl = 300) {
        set_transient($key, $value, $ttl);
    }

    public function delete($key) {
        delete_transient($key);
    }
}
