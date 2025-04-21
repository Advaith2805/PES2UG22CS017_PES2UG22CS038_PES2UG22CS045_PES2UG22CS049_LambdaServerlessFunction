import streamlit as st
import requests
import pandas as pd
import re
import altair as alt

API_BASE = "http://localhost:8000"
st.set_page_config(page_title="Serverless Dashboard", layout="wide")
page = st.sidebar.selectbox("Navigate", ["Function Management", "Monitoring Dashboard"])

def fetch_json(path):
    try:
        res = requests.get(f"{API_BASE}{path}")
        res.raise_for_status()
        return res.json()
    except Exception as e:
        st.error(f"Failed to fetch {path}: {e}")
        return None

# --- Function Management View ---
if page == "Function Management":
    st.header("Function Management")

    with st.expander("Create New Function"):
        with st.form("create_form"):
            name = st.text_input("Name")
            route = st.text_input("Route")
            language = st.selectbox("Language", ["python", "javascript"])
            timeout = st.number_input("Timeout (s)", min_value=0, value=5)
            code = st.text_area("Code", height=200)
            submit = st.form_submit_button("Create Function")
            if submit:
                payload = {"name": name, "route": route, "language": language, "timeout": timeout, "code": code}
                r = requests.post(f"{API_BASE}/functions/", json=payload)
                st.success("Function created.") if r.ok else st.error(f"Error: {r.text}")

    functions = fetch_json("/functions/")
    if functions:
        df = pd.DataFrame(functions)
        st.dataframe(df)

        st.markdown("---")
        st.subheader("Edit / Delete Function")
        func_ids = df["id"].tolist()
        selected = st.selectbox("Select Function ID", func_ids, key="sel_edit") if func_ids else None
        if selected is not None:
            func = next((f for f in functions if f["id"] == selected), None)
            if func:
                with st.form("edit_form"):
                    language_index = ["python", "javascript"].index(func["language"]) if func["language"] in ["python", "javascript"] else 0
                    name2 = st.text_input("Name", value=func["name"])
                    route2 = st.text_input("Route", value=func["route"])
                    lang2 = st.selectbox("Language", ["python", "javascript"], index=language_index)
                    timeout2 = st.number_input("Timeout", value=func["timeout"])
                    code2 = st.text_area("Code", value=func["code"], height=200)
                    if st.form_submit_button("Update Function"):
                        payload = {"name": name2, "route": route2, "language": lang2, "timeout": timeout2, "code": code2}
                        r = requests.put(f"{API_BASE}/functions/{selected}", json=payload)
                        st.success("Function updated.") if r.ok else st.error(f"Error: {r.text}")

                if st.button("Delete Function", key=f"del_{selected}"):
                    r = requests.delete(f"{API_BASE}/functions/{selected}")
                    st.success("Function deleted.") if r.ok else st.error(f"Error: {r.text}")
    else:
        st.info("No functions available.")

    st.markdown("---")
    st.subheader("Execute Function")
    if functions:
        func_ids = [f["id"] for f in functions]
        exec_id = st.selectbox("Function ID to Execute", func_ids, key="exec_func")
        tech = st.selectbox("Execution Technology", ["docker", "gvisor"])
        if st.button("Execute Function"):
            try:
                r = requests.post(f"{API_BASE}/execute/{exec_id}?tech={tech}")
                if r.ok:
                    st.success("Execution complete.")
                    st.json(r.json())
                else:
                    st.error(f"Execution error: {r.text}")
            except Exception as e:
                st.error(f"Execution failed: {e}")
    else:
        st.warning("No functions to execute.")

# --- Monitoring Dashboard View ---
elif page == "Monitoring Dashboard":
    st.header("Monitoring Dashboard")
    try:
        metrics = requests.get(f"{API_BASE}/metrics").text
    except Exception as e:
        st.error(f"Failed to load metrics: {e}")
        st.stop()

    req_counts, err_counts, exec_sums = {}, {}, {}
    cpu_usage, mem_usage = {}, {}

    for line in metrics.splitlines():
        if "function_requests_total" in line:
            m = re.match(r'.*function_id="(\d+)",function_name="([^"]+)",language="([^"]+)",tech="([^"]+)"\} ([\d\.e\+\-]+)', line)
            if m:
                key = tuple(m.groups()[:4])
                req_counts[key] = float(m.group(5))
        elif "function_errors_total" in line:
            m = re.match(r'.*function_id="(\d+)",function_name="([^"]+)",language="([^"]+)",tech="([^"]+)"\} ([\d\.e\+\-]+)', line)
            if m:
                key = tuple(m.groups()[:4])
                err_counts[key] = float(m.group(5))
        elif "function_execution_duration_seconds_sum" in line:
            m = re.match(r'.*function_id="(\d+)",function_name="([^"]+)",language="([^"]+)",tech="([^"]+)"\} ([\d\.e\+\-]+)', line)
            if m:
                key = tuple(m.groups()[:4])
                exec_sums[key] = float(m.group(5))
        elif "container_cpu_usage" in line:
            m = re.match(r'.*container_name="([^"]+)"\} ([\d\.e\+\-]+)', line)
            if m:
                cpu_usage[m.group(1)] = float(m.group(2))
        elif "container_memory_usage" in line:
            m = re.match(r'.*container_name="([^"]+)"\} ([\d\.e\+\-]+)', line)
            if m:
                mem_usage[m.group(1)] = float(m.group(2))

    rows = []
    for key, req in req_counts.items():
        fid, name, lang, tech = key
        err = err_counts.get(key, 0)
        total_time = exec_sums.get(key, 0)
        avg_time = total_time / req if req else 0
        rows.append({
            "function_id": fid,
            "function_name": name,
            "language": lang,
            "tech": tech,
            "requests": req,
            "errors": err,
            "error_rate": err / req if req else 0,
            "avg_latency_s": avg_time
        })

    func_df = pd.DataFrame(rows)

    if not func_df.empty:
        total_req = func_df["requests"].sum()
        total_err = func_df["errors"].sum()
        avg_lat = (func_df["avg_latency_s"] * func_df["requests"]).sum() / total_req if total_req else 0
        err_rate = total_err / total_req if total_req else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Requests", int(total_req))
        c2.metric("Total Errors", int(total_err))
        c3.metric("Error Rate", f"{err_rate:.2%}")
        c4.metric("Avg Latency (s)", f"{avg_lat:.3f}")

        st.markdown("### Function Performance")
        st.dataframe(func_df)

        chart = alt.Chart(func_df).mark_bar().encode(
            x='function_name:N',
            y='requests:Q',
            color='tech:N',
            tooltip=['function_name', 'language', 'tech', 'requests', 'errors', 'avg_latency_s']
        )
        st.altair_chart(chart, use_container_width=True)

        st.markdown("### Container Resource Utilization")
        cols = st.columns(2)
        with cols[0]:
            st.write("CPU Usage")
            if cpu_usage:
                cpu_df = pd.DataFrame([{"container": k, "cpu": v} for k, v in cpu_usage.items()])
                st.bar_chart(cpu_df.set_index("container"))
        with cols[1]:
            st.write("Memory Usage")
            if mem_usage:
                mem_df = pd.DataFrame([{"container": k, "memory": v} for k, v in mem_usage.items()])
                st.bar_chart(mem_df.set_index("container"))
    else:
        st.info("No metric data available.")
