import streamlit as st  # type:ignore
import requests  # type:ignore

# Backend API URL
BACKEND_URL = "http://127.0.0.1:8000"  # Update this if the backend runs on a different host or port

st.title("Serverless Function Execution Platform")

# Tabbed interface for different functionalities
tab1, tab2, tab3, tab4 = st.tabs(["Create Function", "View Functions", "Execute Function", "Metrics"])

# Tab 1: Create Function
with tab1:
    st.header("Create a New Function")
    name = st.text_input("Function Name")
    route = st.text_input("Route")
    language = st.selectbox("Language", ["python", "javascript"])
    timeout = st.number_input("Timeout (seconds)", min_value=1, value=5)
    code = st.text_area("Function Code")

    if st.button("Create Function"):
        payload = {
            "name": name,
            "route": route,
            "language": language,
            "timeout": timeout,
            "code": code,
        }
        response = requests.post(f"{BACKEND_URL}/functions/", json=payload)
        if response.status_code == 200:
            st.success("Function created successfully!")
        else:
            st.error(f"Error: {response.json().get('detail', 'Unknown error')}")

# Tab 2: View Functions
with tab2:
    st.header("View All Functions")
    response = requests.get(f"{BACKEND_URL}/functions/")
    if response.status_code == 200:
        functions = response.json()
        for function in functions:
            st.subheader(f"Function: {function['name']}")
            st.write(f"Route: {function['route']}")
            st.write(f"Language: {function['language']}")
            st.write(f"Timeout: {function['timeout']} seconds")
            st.code(function['code'], language=function['language'])
    else:
        st.error("Failed to fetch functions.")

# Tab 3: Execute Function
with tab3:
    st.header("Execute a Function")
    function_id = st.number_input("Function ID", min_value=1, step=1)
    tech = st.selectbox("Virtualization Technology", ["docker", "gvisor"])
    input_data = st.text_area("Input Data (JSON format)")

    if st.button("Execute Function"):
        try:
            input_json = input_data.strip()
            payload = {"input_data": input_json}
            response = requests.post(f"{BACKEND_URL}/execute/{function_id}?tech={tech}", json=payload)
            if response.status_code == 200:
                result = response.json()
                st.success("Function executed successfully!")
                st.write("Output:")
                st.code(result.get("output", ""))
                if result.get("error"):
                    st.error(f"Error: {result['error']}")
            else:
                st.error(f"Error: {response.json().get('detail', 'Unknown error')}")
        except Exception as e:
            st.error(f"Invalid input data: {e}")

# Tab 4: Metrics
with tab4:
    st.header("System Metrics")
    response = requests.get(f"{BACKEND_URL}/metrics")
    if response.status_code == 200:
        metrics_data = response.text
        st.text_area("Metrics", metrics_data, height=400)
    else:
        st.error("Failed to fetch metrics.")