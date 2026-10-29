<template>
  <div>
    <!-- Top Breadcrumb & Actions -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted);">
        <router-link to="/vendors" style="color: var(--purple); text-decoration: none; font-weight: 700;">← Back to Vendors</router-link>
        <span>/</span>
        <span>Vendor Master</span>
        <span>/</span>
        <strong style="color: var(--ink);">{{ vendorId || 'New Vendor Registration' }}</strong>
        <span v-if="!isSaved" style="background: #fff3d7; color: #bf7b00; font-size: 10px; font-weight: 800; padding: 2px 7px; border-radius: 6px;">Draft</span>
      </div>

      <div style="display: flex; gap: 8px;">
        <router-link to="/vendors" class="secondary-btn" style="text-decoration: none; padding: 8px 14px; font-size: 11px;">Cancel</router-link>
        <button class="primary-btn" style="padding: 8px 16px; font-size: 11px;" @click="handleSave">Save Vendor</button>
      </div>
    </div>

    <!-- Onboarding & Compliance Stepper -->
    <div style="background: rgba(255,255,255,0.9); border: 1px solid #e7e8f8; border-radius: 18px; padding: 14px 18px; margin-bottom: 20px; box-shadow: var(--shadow); overflow-x: auto;">
      <div style="display: flex; align-items: center; justify-content: space-between; min-width: 680px; gap: 8px;">
        <div v-for="(step, idx) in steps" :key="step.title" style="display: flex; align-items: center; gap: 10px; flex: 1; padding: 8px 12px; border-radius: 12px; background: currentStep === idx + 1 ? '#eee9ff' : 'transparent'; border: currentStep === idx + 1 ? '1px solid #d4c8ff' : 'none';">
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
      <!-- Section 1: Basic Vendor Information -->
      <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
        1. Primary Vendor Information
      </h3>

      <div class="form-grid" style="margin-bottom: 24px;">
        <div class="field full">
          <label>Vendor / Supplier Legal Name *</label>
          <input v-model="formData.name" placeholder="Grand Convention Center & Resort Pvt Ltd" />
        </div>
        <div class="field">
          <label>Supplier Group / Category *</label>
          <select v-model="formData.category">
            <option>Travel & Hospitality</option>
            <option>IT & Software Services</option>
            <option>Marketing & Advertising</option>
            <option>Office Supplies & Printing</option>
            <option>Legal & Professional Consultancy</option>
          </select>
        </div>
        <div class="field">
          <label>Company Type</label>
          <select v-model="formData.companyType">
            <option>Private Limited</option>
            <option>Proprietorship</option>
            <option>Partnership / LLP</option>
            <option>Public Limited</option>
          </select>
        </div>
      </div>

      <!-- Section 2: Statutory Tax & Compliance -->
      <div style="border-top: 1px solid #edf0fa; padding-top: 20px;">
        <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
          2. Statutory Tax & Compliance
        </h3>

        <div class="form-grid" style="margin-bottom: 24px;">
          <div class="field">
            <label>GSTIN (15-Character) *</label>
            <input v-model="formData.gstin" placeholder="33AAACG0001AZ3" @input="extractPanFromGstin" />
            <small style="color: var(--muted); font-size: 9px;">Format: 2 State digits + 10 PAN chars + 1 entity + 1 Z + 1 check</small>
          </div>
          <div class="field">
            <label>Permanent Account Number (PAN) *</label>
            <input v-model="formData.pan" placeholder="AAACG0001A" />
          </div>
          <div class="field">
            <label>Default Statutory TDS Section *</label>
            <select v-model="formData.tdsSection">
              <option>194C - Contractor Payments (1% / 2%)</option>
              <option>194J - Professional & Technical Fees (10%)</option>
              <option>194I - Rent of Land / Building (10%)</option>
              <option>194H - Commission / Brokerage (5%)</option>
              <option>No TDS Applicable (Threshold / Exemption Certificate)</option>
            </select>
          </div>
          <div class="field">
            <label>MSME Udyam Registration #</label>
            <input v-model="formData.msme" placeholder="UDYAM-TN-01-0012345" />
          </div>
        </div>
      </div>

      <!-- Section 3: Bank Account Details & Penny-Drop Verification -->
      <div style="border-top: 1px solid #edf0fa; padding-top: 20px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
          <h3 style="margin: 0; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
            3. Banking Payout Details
          </h3>
          <span style="font-size: 11px; font-weight: 750; color: #08a96a; background: #ddfbef; padding: 4px 10px; border-radius: 999px;">
            ✓ Penny-Drop Verified
          </span>
        </div>

        <div class="form-grid" style="margin-bottom: 24px;">
          <div class="field">
            <label>Beneficiary Account Holder Name *</label>
            <input v-model="formData.bankBeneficiary" placeholder="Grand Convention Center Pvt Ltd" />
          </div>
          <div class="field">
            <label>Bank Name *</label>
            <input v-model="formData.bankName" placeholder="HDFC Bank" />
          </div>
          <div class="field">
            <label>Account Number *</label>
            <input v-model="formData.accountNumber" placeholder="50200012345678" />
          </div>
          <div class="field">
            <label>IFSC Code (11-Character) *</label>
            <input v-model="formData.ifsc" placeholder="HDFC0001234" />
          </div>
        </div>
      </div>

      <!-- Section 4: Contact & Registered Office -->
      <div style="border-top: 1px solid #edf0fa; padding-top: 20px;">
        <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
          4. Contact & Registered Office
        </h3>

        <div class="form-grid">
          <div class="field">
            <label>Primary Contact Person</label>
            <input v-model="formData.contactPerson" placeholder="Ramesh Krishnan" />
          </div>
          <div class="field">
            <label>Contact Phone / Mobile</label>
            <input v-model="formData.contactPhone" placeholder="+91 98401 23456" />
          </div>
          <div class="field full">
            <label>Registered Office Address</label>
            <textarea v-model="formData.address" rows="2" placeholder="123 Marina Beach Road, Chennai - 600028"></textarea>
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

const vendorId = computed(() => route.params.id || '');
const isSaved = ref(false);
const currentStep = ref(3);

const steps = [
  { title: 'Onboarding', subtitle: 'Basic Profile' },
  { title: 'Tax Validation', subtitle: 'GSTIN & PAN' },
  { title: 'Bank Verification', subtitle: 'Penny-Drop Match' },
  { title: 'Active Supplier', subtitle: 'Ready for PO/Invoices' },
];

const formData = ref({
  name: 'Grand Convention Center & Resort Pvt Ltd',
  category: 'Travel & Hospitality',
  companyType: 'Private Limited',
  gstin: '33AAACG0001AZ3',
  pan: 'AAACG0001A',
  tdsSection: '194C - Contractor Payments (1% / 2%)',
  msme: 'UDYAM-TN-02-0044551',
  bankBeneficiary: 'Grand Convention Center & Resort Pvt Ltd',
  bankName: 'HDFC Bank',
  accountNumber: '50200088991122',
  ifsc: 'HDFC0000123',
  contactPerson: 'Ramesh Krishnan (Sales Director)',
  contactPhone: '+91 98401 23456',
  address: '123 East Coast Road, Mahabalipuram, Chennai, Tamil Nadu 603104',
});

function extractPanFromGstin() {
  if (formData.value.gstin && formData.value.gstin.length >= 12) {
    formData.value.pan = formData.value.gstin.slice(2, 12);
  }
}

function handleSave() {
  isSaved.value = true;
  emitToast('Vendor profile saved successfully.');
}
</script>

