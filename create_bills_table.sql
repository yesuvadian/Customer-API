-- =====================================================
-- BILLS TABLE FOR LOCAL STORAGE
-- =====================================================

-- Create bills table
CREATE TABLE IF NOT EXISTS bills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bill_number VARCHAR(50) NOT NULL,
    payment_id VARCHAR(50) NOT NULL,
    invoice_id VARCHAR(50) NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    vendor_id UUID,
    status VARCHAR(20) DEFAULT 'open',
    reference_number VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_bills_payment_id ON bills(payment_id);
CREATE INDEX IF NOT EXISTS idx_bills_invoice_id ON bills(invoice_id);
CREATE INDEX IF NOT EXISTS idx_bills_vendor_id ON bills(vendor_id);
CREATE INDEX IF NOT EXISTS idx_bills_status ON bills(status);
CREATE INDEX IF NOT EXISTS idx_bills_created_at ON bills(created_at);

-- Add table comments
COMMENT ON TABLE bills IS 'Local bills created from payments';
COMMENT ON COLUMN bills.id IS 'Unique identifier for the bill';
COMMENT ON COLUMN bills.bill_number IS 'Bill number (e.g., BILL-79)';
COMMENT ON COLUMN bills.payment_id IS 'Zoho Books payment ID';
COMMENT ON COLUMN bills.invoice_id IS 'Zoho Books invoice ID';
COMMENT ON COLUMN bills.amount IS 'Bill amount';
COMMENT ON COLUMN bills.vendor_id IS 'Internal vendor UUID from users table';
COMMENT ON COLUMN bills.status IS 'Bill status: open, paid, void';
COMMENT ON COLUMN bills.reference_number IS 'Reference number from payment';
COMMENT ON COLUMN bills.created_at IS 'When the bill was created';
COMMENT ON COLUMN bills.updated_at IS 'When the bill was last updated';
-- Add missing columns
ALTER TABLE bills ADD COLUMN IF NOT EXISTS bill_number VARCHAR(255);
ALTER TABLE bills ADD COLUMN IF NOT EXISTS payment_id VARCHAR(255);
ALTER TABLE bills ADD COLUMN IF NOT EXISTS vendor_id UUID;
ALTER TABLE bills ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE bills ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();