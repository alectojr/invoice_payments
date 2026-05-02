# brilliant_invoices.py - QR Code with Full Details (No Link Issue)
from datetime import datetime
import webbrowser
import os
import qrcode
from io import BytesIO
import base64

class BrilliantInvoice:
    def __init__(self):
        self.invoice_count = 1
        print("🚗 Brilliant Driving School - Invoice System")
        print("=" * 70)

    def generate_invoice_number(self):
        today = datetime.now().strftime("%Y%m%d")
        num = f"{self.invoice_count:04d}"
        self.invoice_count += 1
        return f"BDS-{today}-{num}"

    def clean_amount(self, amount_str):
        return int(amount_str.replace(',', '').replace(' ', ''))

    def record_payment(self):
        print("\n" + "-"*70)
        print("               NEW PAYMENT ENTRY")
        print("-"*70)

        student_name = input("Student Full Name: ").strip()
        course = input("Course (Basic / HGV / PSV): ").strip().upper()
        payment_type = input("Payment Type: ").strip()
        
        while True:
            amount_str = input("Amount Paid (TSh): ").strip()
            try:
                amount = self.clean_amount(amount_str)
                break
            except:
                print("❌ Please enter numbers only")

        invoice_no = self.generate_invoice_number()
        date_str = datetime.now().strftime("%d %B %Y, %H:%M")

        # Full details for QR Code
        qr_text = f"""Brilliant Driving School
Invoice: {invoice_no}
Date: {date_str}
Student: {student_name}
Course: {course}
Payment: {payment_type}
Amount: {amount:,} TSh

✅ Valid Invoice"""

        # Generate QR
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()

        # Main Invoice
        html_content = f"""
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Invoice {invoice_no}</title>
            <style>
                body {{ font-family: Arial; margin: 20px; background: #f4f6f9; }}
                .invoice {{ max-width: 800px; margin: auto; background: white; padding: 30px; border-radius: 15px; box-shadow: 0 0 20px rgba(0,0,0,0.1); }}
                h1 {{ text-align: center; color: #1e3a8a; }}
                .amount {{ font-size: 26px; font-weight: bold; color: #27ae60; text-align: center; }}
                .qr {{ text-align: center; margin: 25px 0; }}
            </style>
        </head>
        <body>
            <div class="invoice">
                <h1>BRILLIANT DRIVING SCHOOL</h1>
                <h2>OFFICIAL PAYMENT INVOICE</h2>
                <hr>
                <p><strong>Invoice:</strong> {invoice_no}</p>
                <p><strong>Date:</strong> {date_str}</p>
                <p><strong>Student:</strong> {student_name}</p>
                <p><strong>Course:</strong> {course}</p>
                <p><strong>Payment:</strong> {payment_type}</p>
                <div class="amount">Amount Paid: {amount:,} TSh</div>
                
                <div class="qr">
                    <img src="data:image/png;base64,{qr_base64}" width="200"><br>
                    <strong>Scan QR to Verify</strong>
                </div>
            </div>
        </body>
        </html>
        """

        filename = f"Invoice_{invoice_no}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"\n✅ Invoice {invoice_no} generated!")
        print(f"📄 Saved: {filename}")

        webbrowser.open('file://' + os.path.realpath(filename))

    def run(self):
        while True:
            print("\n1. Create New Invoice")
            print("2. Exit")
            choice = input("\nChoose (1/2): ").strip()
            if choice == "1":
                self.record_payment()
            elif choice == "2":
                print("\nGoodbye!")
                break

if __name__ == "__main__":
    system = BrilliantInvoice()
    system.run()