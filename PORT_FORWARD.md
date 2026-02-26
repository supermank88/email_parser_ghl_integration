# Opening the app when using Cursor (remote server)

The Django server runs on the **remote** machine. Your browser runs on **your** machine. So `http://localhost:8000` in the browser tries **your** port 8000, which has nothing running.

## Fix: Forward port 8000 in Cursor

1. **Open the Ports panel**
   - Bottom panel → **PORTS** tab  
   - Or: **View** → **Ports**

2. **Forward port 8000**
   - Click **"Forward a Port"** (or the **+**).
   - Enter **8000** and press Enter.
   - You should see **8000** with visibility **Public** or **Private**.

3. **Open the app**
   - In the Ports list, find **8000**.
   - Click **"Open in Browser"** (globe icon) on that row,  
     **or** in your browser go to: **http://localhost:8000**

4. **Direct link to NDA**
   - **http://localhost:8000/inbound/nda/contacts/**

If "Open in Browser" uses a different URL (e.g. a Cursor tunnel), use that URL instead.
