<template>
  <aside class="sidebar">
    <router-link to="/vendor-claims" class="brand">
      <div class="brand-mark">▣</div>
      <div class="brand-copy">
        <div class="brand-name">AP Automation</div>
        <div class="brand-sub">Accounts Payable</div>
      </div>
    </router-link>

    <div class="nav-label">Workspace</div>

    <nav class="nav" aria-label="Main navigation">
      <router-link
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: currentPath.startsWith(item.path) }"
      >
        <span class="ico">{{ item.icon }}</span>
        <span class="nav-text">{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="sidebar-spacer"></div>

    <div class="help-card">
      <div class="help-icon">✳</div>
      <strong>Need Help?</strong>
      <p>Check guides or raise a request. Our AP support team is here to help.</p>
      <button class="btn-outline" @click="$emit('support')">↗ &nbsp; Contact Support</button>
    </div>

    <div class="profile">
      <div class="avatar">{{ userInitials }}</div>
      <div class="profile-copy">
        <strong>{{ userName }}</strong>
        <small>{{ userEmail }}</small>
      </div>
      <a href="/app" title="Back to Frappe Desk" class="more">⌄</a>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { initials } from '../utils/api';

const route = useRoute();
const currentPath = computed(() => route.path);

const navItems = [
  { label: 'Dashboard', path: '/dashboard', icon: '⌂' },
  { label: 'Petty Cash', path: '/petty-cash', icon: '💵' },
  { label: 'Vendor Invoice Claim', path: '/vendor-claims', icon: '▤' },
  { label: 'Employee Claims', path: '/employee-claims', icon: '♙' },
  { label: 'Vendor Master', path: '/vendors', icon: '▦' },
  { label: 'Purchase Orders', path: '/purchase-orders', icon: '▣' },
  { label: 'GRN / Goods Receipt', path: '/grn', icon: '▧' },
  { label: 'Event Spends', path: '/event-spends', icon: '◉' },
  { label: 'Payment Batches', path: '/payment-batches', icon: '▣' },
  { label: 'Reports', path: '/reports', icon: '▤' },
  { label: 'Settings', path: '/settings', icon: '⚙' },
];

const userName = computed(() => window.user_fullname || 'Administrator');
const userEmail = computed(() => window.user_email || 'admin@example.com');
const userInitials = computed(() => initials(userName.value));
</script>
