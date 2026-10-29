<template>
  <div>
    <!-- Top Breadcrumb & Actions -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted);">
        <router-link to="/purchase-orders" style="color: var(--purple); text-decoration: none; font-weight: 700;">← Back to Purchase Orders</router-link>
        <span>/</span>
        <span>AP Purchase Order</span>
        <span>/</span>
        <strong style="color: var(--ink);">{{ poId || 'New Purchase Order' }}</strong>
      </div>

      <div style="display: flex; gap: 8px;">
        <button class="small-btn" @click="emitToast('Generating formal PO PDF document...')">⇩ Download PO PDF</button>
        <button class="primary-btn" style="padding: 8px 16px; font-size: 11px;" @click="handleSave">Save PO</button>
      </div>
    </div>

    <!-- 4-Step PO Lifecycle Stepper -->
    <div style="background: rgba(255,255,255,0.9); border: 1px solid #e7e8f8; border-radius: 18px; padding: 14px 18px; margin-bottom: 20px; box-shadow: var(--shadow); overflow-x: auto;">
      <div style="display: flex; align-items: center; justify-content: space-between; min-width: 680px; gap: 8px;">
        <div v-for="(step, idx) in steps" :key="step.title" style="display: flex; align-items: center; gap: 10px; flex: 1; padding: 8px 12px; border-radius: 12px; background: currentStep >= idx + 1 ? '#eee9ff' : 'transparent'; border: currentStep === idx + 1 ? '1px solid #d4c8ff' : 'none';">
          <div
            :style="{
              width: '26px',
              height: '26px',
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              fontSize: '11px',
              fontWeight: '800',
              background: currentStep >= idx + 1 ? 'linear-gradient(135deg, #704cff, #542ff0)' : '#f0f1fa',
              color: currentStep >= idx + 1 ? 'white' : '#7b83a3',
            }"
          >
            {{ idx + 1 }}
          </div>
          <div>
            <div style="font-size: 11px; font-weight: 800; color: var(--ink);">{{ step.title }}</div>
            <div style="font-size: 9px; color: var(--muted);">{{ step.subtitle }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Main Container -->
    <div style="background: rgba(255,255,255,0.92); border: 1px solid #e7e8f8; border-radius: 20px; padding: 22px; box-shadow: var(--shadow);">
      <!-- PO Header Details -->
      <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
        Purchase Order Header
      </h3>

      <div class="form-grid" style="margin-bottom: 24px;">
        <div class="field">
          <label>PO Number</label>
          <input :value="poData.name" disabled style="background: #f7f8fc; font-weight: 700; color: var(--purple-dark);" />
        </div>
        <div class="field">
          <label>PO Date *</label>
          <input v-model="poData.date" type="date" />
        </div>
        <div class="field">
          <label>Vendor / Supplier *</label>
          <select v-model="poData.vendor">
            <option>Grand Convention Center & Resort</option>
            <option>Tech Corp Solutions India Pvt Ltd</option>
            <option>Event Craft Media</option>
            <option>Office Supplies Co.</option>
          </select>
        </div>
        <div class="field">
          <label>Billed Company *</label>
          <select v-model="poData.company">
            <option>Anshul A Gupta & Associates</option>
            <option>Quanticus Software Solutions</option>
          </select>
        </div>
      </div>

      <!-- Line Items & GRN Fulfillment Table -->
      <div style="border-top: 1px solid #edf0fa; padding-top: 20px;">
        <h3 style="margin: 0 0 14px; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
          Order Items & Goods Receipt (GRN) Status
        </h3>

        <div style="border: 1px solid #e7e8f8; border-radius: 14px; overflow: hidden; margin-bottom: 14px;">
          <table style="width: 100%; border-collapse: collapse; font-size: 11px;">
            <thead style="background: #f8f9ff;">
              <tr>
                <th style="padding: 10px 12px;">#</th>
                <th style="padding: 10px 12px;">ITEM DESCRIPTION</th>
                <th style="padding: 10px 12px;">QTY</th>
                <th style="padding: 10px 12px;">UNIT RATE</th>
                <th style="padding: 10px 12px;">LINE TOTAL</th>
                <th style="padding: 10px 12px;">GRN DELIVERED</th>
                <th style="padding: 10px 12px;">STATUS</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, idx) in poData.items" :key="idx" style="border-top: 1px solid #f0f1fa;">
                <td style="padding: 8px 12px;">{{ idx + 1 }}</td>
                <td style="padding: 8px 12px;"><strong>{{ item.description }}</strong></td>
                <td style="padding: 8px 12px;">{{ item.qty }}</td>
                <td style="padding: 8px 12px;">₹ {{ item.rate.toLocaleString('en-IN') }}</td>
                <td style="padding: 8px 12px; font-weight: 700;">₹ {{ (item.qty * item.rate).toLocaleString('en-IN') }}</td>
                <td style="padding: 8px 12px;">
                  <span style="color: #08a96a; font-weight: 750;">{{ item.deliveredQty }} / {{ item.qty }}</span>
                </td>
                <td style="padding: 8px 12px;">
                  <span class="status approved">GRN Confirmed</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 3-Way Match Verification Card -->
        <div style="padding: 16px; background: #faf9ff; border: 1px solid #e7e0ff; border-radius: 14px; display: flex; justify-content: space-between; align-items: center; margin-top: 18px;">
          <div>
            <strong style="font-size: 12px; color: var(--purple-dark); display: block; margin-bottom: 4px;">
              3-Way Match Status: Passed 100%
            </strong>
            <p style="margin: 0; font-size: 11px; color: var(--muted);">
              PO Values, GRN Received Quantities, and Claim Invoice Lines match perfectly without variance.
            </p>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 11px; color: var(--muted); margin-bottom: 2px;">Total Order Value</div>
            <div style="font-size: 22px; font-weight: 800; color: var(--purple-dark);">
              ₹ {{ totalPoAmount.toLocaleString('en-IN', { maximumFractionDigits: 2 }) }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();
const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const poId = computed(() => route.params.id || 'PO-2026-001');
const currentStep = ref(4);

const steps = [
  { title: 'Draft / PO Prep', subtitle: 'Requisition' },
  { title: 'Approved & Issued', subtitle: 'Finance Sign-off' },
  { title: 'Vendor e-Signed', subtitle: 'Signed Contract' },
  { title: 'GRN & Completed', subtitle: 'Delivered & Matched' },
];

const poData = ref({
  name: poId.value,
  date: '2026-10-20',
  vendor: 'Grand Convention Center & Resort',
  company: 'Anshul A Gupta & Associates',
  items: [
    { description: 'Conference Hall Rental (Day 1)', qty: 1, rate: 150000, deliveredQty: 1 },
    { description: 'Catering Services Buffet (250 pax)', qty: 1, rate: 75000, deliveredQty: 1 },
    { description: 'Audio/Visual Stage Production Package', qty: 1, rate: 20000, deliveredQty: 1 },
  ],
});

const totalPoAmount = computed(() => poData.value.items.reduce((acc, x) => acc + (x.qty * x.rate), 0));

function handleSave() {
  emitToast('Purchase Order saved.');
}
</script>

