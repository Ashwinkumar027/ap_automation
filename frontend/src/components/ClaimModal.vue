<template>
  <div class="modal-backdrop" :class="{ show: modelValue }" @click.self="$emit('update:modelValue', false)">
    <div class="modal">
      <div class="modal-head">
        <div>
          <h2>Create vendor invoice claim</h2>
          <p class="muted">Add invoice information to start the AP approval workflow.</p>
        </div>
        <button class="icon-btn" @click="$emit('update:modelValue', false)">✕</button>
      </div>

      <form @submit.prevent="handleSubmit">
        <div class="form-grid">
          <div class="field">
            <label>Vendor / Supplier *</label>
            <select v-model="form.vendor" required>
              <option value="">Select vendor</option>
              <option v-for="v in vendors" :key="v" :value="v">{{ v }}</option>
            </select>
          </div>

          <div class="field">
            <label>Billed company *</label>
            <select v-model="form.company" required>
              <option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>

          <div class="field">
            <label>Invoice number *</label>
            <input v-model="form.invoice" required placeholder="e.g. INV-2026-001" />
          </div>

          <div class="field">
            <label>Invoice date *</label>
            <input v-model="form.date" type="date" required />
          </div>

          <div class="field">
            <label>Base taxable amount (₹) *</label>
            <input v-model.number="form.amount" type="number" min="1" step="0.01" required placeholder="0.00" />
          </div>

          <div class="field">
            <label>Purchase order number</label>
            <input v-model="form.po" placeholder="e.g. PO-2026-009" />
          </div>

          <div class="field">
            <label>GST rate</label>
            <select v-model="form.gst">
              <option value="18">18%</option>
              <option value="12">12%</option>
              <option value="5">5%</option>
              <option value="0">0%</option>
            </select>
          </div>

          <div class="field">
            <label>Payment terms</label>
            <select v-model="form.terms">
              <option>Net 30 Days</option>
              <option>Net 15 Days</option>
              <option>Due on receipt</option>
              <option>Net 45 Days</option>
            </select>
          </div>

          <div class="field full">
            <label>Notes (optional)</label>
            <textarea v-model="form.notes" rows="2" placeholder="Add invoice notes or context..."></textarea>
          </div>
        </div>

        <div class="modal-footer">
          <button type="button" class="secondary-btn" @click="$emit('update:modelValue', false)">Cancel</button>
          <button type="submit" class="primary-btn" :disabled="submitting">
            {{ submitting ? 'Submitting...' : 'Create claim →' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  vendors: {
    type: Array,
    default: () => [
      'Grand Convention Center & Resort',
      'Tech Corp Solutions India Pvt Ltd',
      'Event Craft Media',
      'Office Supplies Co.',
      'Travel Partner India',
      'Digital Media Works',
      'Quanticus Software Solutions',
      'Print Hub India',
    ],
  },
  companies: {
    type: Array,
    default: () => (window.companies && window.companies.length ? window.companies : ['Anshul A Gupta & Associates', 'Quanticus Software Solutions']),
  },
});

const emit = defineEmits(['update:modelValue', 'create']);
const submitting = ref(false);

const form = reactive({
  vendor: '',
  company: props.companies[0] || '',
  invoice: '',
  date: new Date().toISOString().split('T')[0],
  amount: null,
  po: '',
  gst: '18',
  terms: 'Net 30 Days',
  notes: '',
});

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      form.vendor = '';
      form.invoice = '';
      form.amount = null;
      form.po = '';
      form.notes = '';
      form.date = new Date().toISOString().split('T')[0];
    }
  }
);

async function handleSubmit() {
  if (!form.vendor || !form.company || !form.invoice || !form.amount) return;
  submitting.value = true;
  try {
    emit('create', { ...form });
    emit('update:modelValue', false);
  } finally {
    submitting.value = false;
  }
}
</script>

