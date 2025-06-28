from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, session, make_response, jsonify
import os
import glob
import pandas as pd
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from .logai_handler import process_log_file
import numpy as np

main = Blueprint('main', __name__)

@main.before_request
def before_request():
    """Set cache headers to prevent caching issues"""
    if request.endpoint == 'main.analyzed_logs':
        # Set headers but don't return response - let the route handle it
        pass

def compute_dashboard_metrics():
    """Compute dashboard metrics from all previous analysis results"""
    uploads_dir = 'uploads'
    anomaly_files = glob.glob(os.path.join(uploads_dir, 'anomaly_results_*.csv'))
    
    total_logs = 0
    total_anomalies = 0
    total_processing_time = 0
    file_count = 0
    processing_times = []
    
    for file_path in anomaly_files:
        try:
            df = pd.read_csv(file_path)
            if not df.empty:
                total_logs += len(df)
                if 'is_anomaly' in df.columns:
                    total_anomalies += df['is_anomaly'].sum()
                
                # Get processing time if available
                if 'processing_time_seconds' in df.columns:
                    processing_time = df['processing_time_seconds'].iloc[0]  # Same for all rows in file
                    processing_times.append(processing_time)
                    total_processing_time += processing_time
                
                file_count += 1
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    
    # Calculate metrics
    success_rate = ((total_logs - total_anomalies) / total_logs * 100) if total_logs > 0 else 0
    
    # Calculate average processing time
    if processing_times:
        avg_processing_time = sum(processing_times) / len(processing_times)
    else:
        avg_processing_time = 2.4  # Default fallback
    
    # Calculate month-over-month change (simplified)
    # For now, we'll use a simple calculation based on file count
    if file_count > 0:
        # Estimate based on number of files processed
        growth_rate = min(15.1, max(-10, (file_count - 1) * 5))  # Between -10% and +15%
    else:
        growth_rate = 0
    
    return {
        'total_logs': total_logs,
        'total_anomalies': total_anomalies,
        'success_rate': round(success_rate, 1),
        'avg_processing_time': round(avg_processing_time, 1),
        'growth_rate': growth_rate,
        'files_processed': file_count
    }

@main.route('/', methods=['GET', 'POST'])
def index():
    # Compute dashboard metrics
    dashboard_metrics = compute_dashboard_metrics()

    if request.method == 'POST':
        print("📝 POST request received")
        print(f"   - Content-Type: {request.content_type}")
        print(f"   - Form data keys: {list(request.form.keys())}")
        print(f"   - Files: {list(request.files.keys())}")
        
        parser = request.form.get("parser", "drain")
        model = request.form.get("model", "isolation_forest")
        user_index = request.form.get("index_name", "").strip()
        index_name = user_index if user_index else f"logai-{datetime.utcnow().strftime('%Y-%m-%d')}"
        
        print(f"   - Parser: {parser}")
        print(f"   - Model: {model}")
        print(f"   - Index: {index_name}")

        file = request.files.get('logfile')
        if not file:
            print("❌ No file uploaded")
            return jsonify({'error': 'No file uploaded.'}), 400

        filename = secure_filename(file.filename or 'unknown_file')
        filepath = os.path.join('uploads', filename)
        print(f"   - Saving file: {filepath}")
        file.save(filepath)
        print(f"   - File saved successfully")

        try:
            print("🔍 Starting log analysis...")
            result_data, csv_path = process_log_file(filepath, parser, model, index_name)
            print("✅ Log analysis completed successfully")
        except KeyError as e:
            print(f"❌ KeyError during analysis: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            print(f"❌ Exception during analysis: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Error during analysis: {str(e)}'}), 500

        print("📊 Processing results...")
        num_logs = len(result_data)
        num_anomalies = result_data["is_anomaly"].sum()
        print(f"   - Total logs: {num_logs}")
        print(f"   - Anomalies: {num_anomalies}")

        if "timestamp" not in result_data.columns or result_data["timestamp"].isnull().all():
            print("⚠️ Timestamp column missing in file — using system time instead.")

        # Store results in session for the results page
        print("💾 Converting results to JSON-serializable format...")
        # Convert DataFrame to JSON-serializable format
        results_dict = []
        for _, row in result_data.iterrows():
            row_dict = {}
            for col, value in row.items():
                if pd.isna(value):
                    row_dict[col] = None
                elif hasattr(value, 'item'):  # Handle numpy types
                    row_dict[col] = value.item()
                else:
                    row_dict[col] = str(value)
            results_dict.append(row_dict)
        
        print(f"💾 Converted {len(results_dict)} results to JSON format")
        print("💾 Storing data in session...")
        print(f"   - Session before storing: {list(session.keys())}")
        
        session.permanent = True  # Make session permanent
        session['analysis_results'] = results_dict
        session['csv_path'] = csv_path
        session['kibana_url'] = f"http://localhost:5601/app/discover#/?_a=(index:'{index_name}',columns:!(_source))"
        session['analysis_summary'] = {
            'total_logs': int(num_logs),
            'total_anomalies': int(num_anomalies),
            'success_rate': round(((num_logs - num_anomalies) / num_logs * 100), 1),
            'index_name': index_name
        }
        
        print(f"   - Session after storing: {list(session.keys())}")
        print(f"   - Analysis results count: {len(session.get('analysis_results', []))}")
        print(f"   - CSV path in session: {session.get('csv_path')}")
        print(f"   - Analysis summary in session: {session.get('analysis_summary')}")

        print(f"✅ Analysis completed successfully. Results stored in session.")
        print(f"   - Total logs: {num_logs}")
        print(f"   - Anomalies: {num_anomalies}")
        print(f"   - Results count: {len(results_dict)}")
        print(f"   - Session keys: {list(session.keys())}")

        # Use traditional redirect instead of JSON response
        flash(f"✅ {num_logs} log entries processed. {num_anomalies} anomalies detected. Sent to index: {index_name}")
        print("🔄 Redirecting to /analyzed-logs...")
        return redirect(url_for('main.analyzed_logs'))

    return render_template('index.html', metrics=dashboard_metrics)

@main.route('/analyzed-logs')
def analyzed_logs():
    """Display analysis results with pagination"""
    print("🔍 Analyzed logs route called")
    print(f"   - Request method: {request.method}")
    print(f"   - Request URL: {request.url}")
    
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Get results from session
    results = session.get('analysis_results', [])
    csv_path = session.get('csv_path')
    kibana_url = session.get('kibana_url')
    analysis_summary = session.get('analysis_summary', {})
    
    print(f"   - Results in session: {len(results)}")
    print(f"   - CSV path: {csv_path}")
    print(f"   - Analysis summary: {analysis_summary}")
    print(f"   - All session keys: {list(session.keys())}")
    
    if not results:
        print("❌ No results found in session, redirecting to index")
        flash('No analysis results found. Please upload and analyze a log file first.')
        return redirect(url_for('main.index'))
    
    # Ensure timestamps are strings to prevent template errors
    for result in results:
        if 'timestamp' in result and result['timestamp'] is not None:
            if isinstance(result['timestamp'], (int, float)):
                # Convert Unix timestamp to ISO format
                result['timestamp'] = datetime.fromtimestamp(result['timestamp']).isoformat()
            elif not isinstance(result['timestamp'], str):
                # Convert any other type to string
                result['timestamp'] = str(result['timestamp'])
    
    # Pagination
    total_results = len(results)
    total_pages = (total_results + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_results = results[start_idx:end_idx]
    
    # Set cache headers to prevent caching issues
    response = make_response(render_template('analyzed_logs.html', 
                         results=paginated_results,
                         csv_path=csv_path,
                         kibana_url=kibana_url,
                         analysis_summary=analysis_summary,
                         pagination={
                             'page': page,
                             'per_page': per_page,
                             'total_pages': total_pages,
                             'total_results': total_results,
                             'start_idx': start_idx + 1,
                             'end_idx': min(end_idx, total_results)
                         }))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@main.route('/download/<filename>')
def download_csv(filename):
    """Download the analysis results CSV file"""
    try:
        file_path = os.path.join('uploads', filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=filename)
        else:
            flash('File not found.')
            return redirect(url_for('main.index'))
    except Exception as e:
        flash(f'Error downloading file: {str(e)}')
        return redirect(url_for('main.index'))

@main.route('/test-upload')
def test_upload():
    """Serve test upload page for debugging"""
    return send_file('test_upload.html')

@main.route('/test-session')
def test_session():
    """Test route to verify session functionality"""
    session['test_data'] = 'Hello from session!'
    session['test_timestamp'] = datetime.now().isoformat()
    return jsonify({
        'session_keys': list(session.keys()),
        'test_data': session.get('test_data'),
        'test_timestamp': session.get('test_timestamp')
    })

@main.route('/debug-session')
def debug_session():
    """Debug route to check session data"""
    return {
        'session_keys': list(session.keys()),
        'analysis_results_count': len(session.get('analysis_results', [])),
        'csv_path': session.get('csv_path'),
        'analysis_summary': session.get('analysis_summary', {})
    }
