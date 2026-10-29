<template>
  <div class="modal-backdrop" :class="{ show: modelValue }" @click.self="$emit('update:modelValue', false)">
    <div class="modal" v-if="claim">
      <div class="modal-head">
        <div>
          <h2>{{ claim.id }}</h2>
          <p class="muted">{{ claim.vendor }} · {{ claim.status }}</p>
        </div>
        <button class="icon-btn" @click="$emit('update:modelValue', false)">✕</button>
      </div>

      <div class="detail-list">
        <div class="detail">
          <small>Invoice number</small>
          <strong>{{ claim.invoice }}</strong>
        </div>
        <div class="detail">
          <small>Vendor / Supplier</small>
          <strong>{{ claim.vendor }}</strong>
        </div>
        <div class="detail">
          <small>Billed company</small>
          <strong>{{ claim.company }}</strong>
        </div>
        <div class="detail">
          <small>Invoice date</small>
          <strong>{{ claim.date }}</strong>
        </div>
        <div class="detail">
          <small>Invoice amount</small>
          <strong class="amount">{{ formatMoney(claim.amount) }}</strong>
        </div>
        <div class="detail">
          <small>Purchase order</small>
          <strong style="color: #6244ed">{{ claim.po || '—' }}</strong>
        </div>
        <div class="detail">
          <small>Status</small>
          <span class="status" :class="statusClass(claim.status)">{{ claim.status }}</span>
        </div>
        <div class="detail">
          <small>Approval level</small>
          <strong>Level {{ claim.level }} of 3</strong>
        </div>
      </div>

      <!-- Disbursal UTR Section if Approved -->
      <div v-if="canDisburse && claim.status === 'Approved'" style="margin-top: 18px; padding: 14px; background: #faf9ff; border: 1px solid #e5e0ff; border-radius: 12px;">
        <strong style="font-size: 12px; color: var(--purple-dark); display: block; margin-bottom: 6px;">
          Disburse Payment (Role Authorized: Payment Releaser / Accounts Director)
        </strong>
        <div style="display: flex; gap: 8px;">
          <input
            v-model="bankUtr"
            placeholder="Enter Bank UTR (e.g. IDFC20261029001)"
            style="flex: 1; padding: 8px 11px; border: 1px solid #dcd4ff; border-radius: 9px; font-size: 11px;"
          />
          <button class="primary-btn" style="padding: 8px 14px; font-size: 11px;" @click="handleDisburse">
            Disburse with UTR
          </button>
        </div>
      </div>

      <div class="modal-footer">
        <button class="secondary-btn" @click="$emit('update:modelValue', false)">Close</button>
        <button
          v-if="!['Approved', 'Paid'].includes(claim.status)"
          class="primary-btn"
          @click="$emit('approve', claim)"
        >
          ✓ Mark approved
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';
import { formatMoney } from '../utils/api';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  claim: { type: Object, default: null },
});

const emit = defineEmits(['update:modelValue', 'approve', 'disburse']);
const bankUtr = ref('');

const userRoles = computed(() => window.user_roles || []);
const canDisburse = computed(() => {
  return (
    userRoles.value.includes('System Manager') ||
    userRoles.value.includes('Payment Releaser') ||
    userRoles.value.includes('Accounts Director')
  );
});

function statusClass(s) {
  if (['Approved', 'Paid'].includes(s)) return 'approved';
  if (s === 'Pending') return 'pending';
  if (['Disputed', 'Rejected'].includes(s)) return 'disputed';
  return 'pending';
}

function handleDisburse() {
  if (!bankUtr.value.trim()) {
    alert('Please enter a valid Bank UTR number.');
    return;
  }
  emit('disburse', { claim: props.claim, utr: bankUtr.value.trim() });
  bankUtr.value = '';
}
</script>

