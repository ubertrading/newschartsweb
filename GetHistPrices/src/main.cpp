#include <chrono>
#include <iomanip>
#include <mutex>
#include <thread>

#include "stdafx.h"

#include <httplib.h>
#include <nlohmann/json.hpp>

#include "CommonSources.h"
#include "LoginParams.h"
#include "ResponseListener.h"
#include "SampleParams.h"
#include "SessionStatusListener.h"

using json = nlohmann::json;
using namespace std;

void printHelp(std::string &);
bool checkObligatoryParams(LoginParams *, SampleParams *);
void printSampleParams(std::string &, LoginParams *, SampleParams *);

void printPrices(IO2GSession *, IO2GResponse *, string &);
bool getHistoryPrices(IO2GSession *, const char *, const char *, DATE, DATE,
                      ResponseListener *, string &);

int read_config(json &config) {

  std::ifstream inFile;
  inFile.open("./GetHistPrices.cfg");

  if (!inFile) {
    cout << "Config file GetHistPrices.cfg missing " << endl;
    return 0;
  }

  std::stringstream strStream;
  strStream << inFile.rdbuf();       // read the file
  std::string str = strStream.str(); // str holds the content of the file

  config = nlohmann::json::parse(str);

  return 1;
}

// Funkcja do konwersji Ole Time na time_point
std::chrono::system_clock::time_point OleTimeToTimePoint(double oleTime) {
  using namespace std::chrono;
  // Dni od epoki Unix (1970-01-01) do epoki OLE (1899-12-30)
  const int daysFromUnixToOLE = 25569;
  // Konwertuj dni OLE na milisekundy od epoki Unix
  auto milliseconds = duration_cast<std::chrono::milliseconds>(
      duration<double>(oleTime - daysFromUnixToOLE) * (24 * 3600) + 1us);
  // Utw�rz time_point na podstawie tych milisekund
  return system_clock::time_point(milliseconds);
}

// Funkcja do formatowania time_point do ci�gu znak�w z milisekundami
std::string FormatTimePoint(const std::chrono::system_clock::time_point &tp) {
  using namespace std::chrono;
  // Pobierz sekundy i milisekundy
  auto seconds = time_point_cast<std::chrono::seconds>(tp);
  auto milliseconds =
      duration_cast<std::chrono::milliseconds>(tp.time_since_epoch()) % 1000;

  // Konwertuj na czas w formacie C
  std::time_t t = system_clock::to_time_t(seconds);
  std::tm tm = *std::gmtime(&t);

  // Sformatuj czas do ci�gu znak�w
  std::ostringstream oss;
  oss << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
  oss << '.' << std::setw(3) << std::setfill('0') << milliseconds.count();
  return oss.str();
}

std::string FormatOleTime(double oleTime) {
  return FormatTimePoint(OleTimeToTimePoint(oleTime));
}

struct Session {
  IO2GSession *session = NULL;
  SessionStatusListener *sessionListener = NULL;
  ResponseListener *responseListener = NULL;

  bool is_ready() const { return session != NULL; }

  void init() {
    session = CO2GTransport::createSession();

    sessionListener = new SessionStatusListener(session, true);
    session->subscribeSessionStatus(sessionListener);

    responseListener = new ResponseListener(session);
    session->subscribeResponse(responseListener);
  }

  void close() {
    session->unsubscribeResponse(responseListener);
    responseListener->release();
    responseListener = NULL;

    session->unsubscribeSessionStatus(sessionListener);
    sessionListener->release();
    sessionListener = NULL;

    session->release();
    session = NULL;
  }

  void reset() {
    close();
    init();
  }
};

int main(int argc, char *argv[]) {
  json config;

  if (!read_config(config)) {
    return 0;
  }

  std::string procName = "GetHistPrices";
  string clogin = config["login"];
  string cpassword = config["password"];
  string curl = config["url"];
  string cconnection = config["connection"];
  LoginParams *loginParams =
      new LoginParams(clogin, cpassword, curl, cconnection);

  /*
  SampleParams *sampleParams = new SampleParams(argc, argv);

  printSampleParams(procName, loginParams, sampleParams);
  if (!checkObligatoryParams(loginParams, sampleParams))
  {
      delete loginParams;
      delete sampleParams;
      return -1;
  }
  */

  httplib::Server svr;

  Session sess;
  sess.init();

  string prices = "";
  string json_res_str = "";
  json result;
  std::mutex request_mutex;

  try {
    svr.Post("/hist/", [=, &sess, &prices, &json_res_str,
                        &result, &request_mutex](const httplib::Request &req,
                                 httplib::Response &res) {
      // Serialize all requests — sess/prices/result are shared state
      std::lock_guard<std::mutex> lock(request_mutex);
      try {
        result.clear();
        json j = json::parse(req.body);

        auto now = std::chrono::system_clock::now();
        std::time_t currentTime = std::chrono::system_clock::to_time_t(now);

        std::cout << std::put_time(std::localtime(&currentTime),
                                   "%Y-%m-%d %H:%M:%S")
                  << " " << j.dump() << std::endl;
        string action = j.value("action", "");

        if (action == "get") {
          string symbol = j["symbol"];
          string timeFrom = j["timeFrom"];
          string timeTo = j["timeTo"];
          string timeframe = j["timeframe"];

          int try_cnt = 0;

          while (true) {
            try_cnt++;
            bool failed = false;

            bool bConnected = sess.sessionListener->isConnected();
            if (!bConnected) {
              bConnected =
                  login(sess.session, sess.sessionListener, loginParams);
            }
            if (bConnected) {
              prices.clear();
              SampleParams *sampleParams =
                  new SampleParams(symbol, timeFrom, timeTo, timeframe);
              if (getHistoryPrices(sess.session, sampleParams->getInstrument(),
                                   sampleParams->getTimeframe(),
                                   sampleParams->getDateFrom(),
                                   sampleParams->getDateTo(),
                                   sess.responseListener, prices)) {
                result["status"] = "OK";
                result["data"] = json::parse(prices);
                delete sampleParams;
                break;
              } else {
                cout << "getHistoryPrices failed" << std::endl;
                failed = true;
              }
            } else {
              cout << "Failed to connect" << std::endl;
              failed = true;
            }

            if (failed) {
              if (try_cnt <= 3) {
                cout << "Retrying " << try_cnt << " of 3..." << std::endl;
                // Do NOT call sess.reset() here — it destroys listener objects
                // while ForexConnect's internal threads may still be firing
                // callbacks into them, causing "pure virtual method called".
                // Instead, logout gracefully and let FC finish its callbacks.
                // The next loop iteration will re-login using the same listeners.
                logout(sess.session, sess.sessionListener);
                std::this_thread::sleep_for(std::chrono::milliseconds(1000));
              } else {
                cout << "Giving up after 3 retries, returning error to caller" << std::endl;
                result["status"] = "ERROR";
                result["data"] = "Failed to fetch prices after 3 retries";
                break;
              }
            }
          }
        } else if (action == "end") {
          exit(1);
        }

      } catch (json::parse_error &e) {
        // Je�li ��danie nie jest prawid�owym JSON, wy�lij odpowied� z b��dem
        res.status = 400;
        result["status"] = "ERROR";
        result["data"] = e.what();
        res.set_content(result.dump(), "text/json");
        return;
      } catch (std::exception &e) {
        res.status = 400;
        result["status"] = "ERROR";
        result["data"] = e.what();
        res.set_content(result.dump(), "text/json");
        return;
      } catch (...) {
        res.status = 400;
        result["status"] = "ERROR";
        result["data"] = "unknown";
        res.set_content(result.dump(), "text/json");
        return;
      }

      json_res_str = result.dump();
      res.set_content(json_res_str, "text/json");
      json_res_str.clear();

      auto now = std::chrono::system_clock::now();
      std::time_t currentTime = std::chrono::system_clock::to_time_t(now);
      cout << std::put_time(std::localtime(&currentTime), "%Y-%m-%d %H:%M:%S")
           << " " << result["status"] << endl;

      result.clear();
    });

    svr.listen(config["listenHost"], config["listenPort"]);
  } catch (std::exception &e) {
    cout << "Fatal exception " << e.what() << endl;
  } catch (...) {
    cout << "Fatal exception " << endl;
  }

  /*
  if (bConnected)
  {
      ResponseListener *responseListener = new ResponseListener(session);
      session->subscribeResponse(responseListener);

      if (!getHistoryPrices(session, sampleParams->getInstrument(),
  sampleParams->getTimeframe(), sampleParams->getDateFrom(),
  sampleParams->getDateTo(), responseListener)) bWasError = true;

      session->unsubscribeResponse(responseListener);
      responseListener->release();
      logout(session, sessionListener);
  }
  else
  {
      bWasError = true;
  }

  session->unsubscribeSessionStatus(sessionListener);
  sessionListener->release();
  session->release();

  delete loginParams;
  delete sampleParams;
  */

  logout(sess.session, sess.sessionListener);

  sess.close();

  delete loginParams;
  return 0;
}

bool getHistoryPrices(IO2GSession *session, const char *sInstrument,
                      const char *sTimeframe, DATE dtFrom, DATE dtTo,
                      ResponseListener *responseListener, string &prices) {

  O2G2Ptr<IO2GRequestFactory> factory = session->getRequestFactory();
  if (!factory) {
    std::cout << "Cannot create request factory" << std::endl;
    return false;
  }
  // find timeframe by identifier
  O2G2Ptr<IO2GTimeframeCollection> timeframeCollection =
      factory->getTimeFrameCollection();
  O2G2Ptr<IO2GTimeframe> timeframe = timeframeCollection->get(sTimeframe);
  if (!timeframe) {
    std::cout << "Timeframe '" << sTimeframe << "' is incorrect!" << std::endl;
    return false;
  }
  std::cout << "Timeframe '" << sTimeframe << " getQueryDepth "
            << timeframe->getQueryDepth() << std::endl;
  O2G2Ptr<IO2GRequest> request =
      factory->createMarketDataSnapshotRequestInstrument(
          sInstrument, timeframe, timeframe->getQueryDepth());
  if (!request) {
    return false;
  }
  DATE dtFirst = dtTo;
  printf("Want data from %s to %s\n", FormatOleTime(dtFrom).c_str(),
         FormatOleTime(dtTo).c_str());
  // there is limit for returned candles amount
  do {
    factory->fillMarketDataSnapshotRequestTime(request, dtFrom, dtFirst, true);
    responseListener->setRequestID(request->getRequestID());
    session->sendRequest(request);
    if (!responseListener->waitEvents()) {
      std::cout << "Response waiting timeout expired" << std::endl;
      return false;
    }
    // shift "to" bound to oldest datetime of returned data
    O2G2Ptr<IO2GResponse> response = responseListener->getResponse();
    if (response && response->getType() == MarketDataSnapshot) {
      O2G2Ptr<IO2GResponseReaderFactory> readerFactory =
          session->getResponseReaderFactory();
      if (readerFactory) {
        O2G2Ptr<IO2GMarketDataSnapshotResponseReader> reader =
            readerFactory->createMarketDataSnapshotReader(response);
        if (reader->size() > 0) {
          printf("Got %i data from %s to %s\n", reader->size(),
                 FormatOleTime(reader->getDate(0)).c_str(),
                 FormatOleTime(reader->getDate(reader->size() - 1)).c_str());
          printPrices(session, response, prices);
          if (dtFrom == reader->getDate(0)) {
            // no more data
            break;
          }
          // data is returned oldest first, so we keep dtFrom fixed and set
          // dtFirst (which is dtTo in the next request) to the earliest time
          // received so far.
          // NB: This works for ticks because FXCM seems to NOT return a tick
          // that is exactly at the dtTo (= dtFirst) time of the request.
          dtFirst = reader->getDate(0);

          // HOWEVER, for bar requests, the FXCM API DOES return bars at the
          // dtTo time, so we have to adjust make it 1 ms less than the earliest
          // time received
          if (reader->isBar()) {
            dtFirst -= 1.0 / (24.0 * 3600.0 * 1000.0);
          }

        } else {
          std::cout << "0 rows received" << std::endl;
          break;
        }
      }
    } else {
      break;
    }
  } while (dtFirst >= dtFrom);

  size_t pos = prices.rfind(',');
  if (pos != std::string::npos) {
    prices.erase(pos, 1);
  }
  prices = "[" + prices + "]";

  return true;
}

void printPrices(IO2GSession *session, IO2GResponse *response, string &prices) {
  if (response != 0) {
    if (response->getType() == MarketDataSnapshot) {
      std::cout << "Request with RequestID='" << response->getRequestID()
                << "' is completed:" << std::endl;
      O2G2Ptr<IO2GResponseReaderFactory> factory =
          session->getResponseReaderFactory();
      if (factory) {
        O2G2Ptr<IO2GMarketDataSnapshotResponseReader> reader =
            factory->createMarketDataSnapshotReader(response);
        if (reader) {
          char sTime[20];
          for (int ii = reader->size() - 1; ii >= 0; ii--) {
            DATE dt = reader->getDate(ii);

            // formatDate(dt, sTime);
            auto tp = OleTimeToTimePoint(dt);
            string sTime = FormatTimePoint(tp);
            if (reader->isBar()) {
              // printf("DateTime=%s, BidOpen=%f, BidHigh=%f, BidLow=%f,
              // BidClose=%f, AskOpen=%f, AskHigh=%f, AskLow=%f, AskClose=%f,
              // Volume=%i\n",
              //     dt, reader->getBidOpen(ii), reader->getBidHigh(ii),
              //     reader->getBidLow(ii), reader->getBidClose(ii),
              //         reader->getAskOpen(ii), reader->getAskHigh(ii),
              //         reader->getAskLow(ii), reader->getAskClose(ii),
              //         reader->getVolume(ii));

              char buffer[512];
              snprintf(buffer, sizeof(buffer),
                       "{\"DateTime\":\"%s\", \"BidOpen\":%f, \"BidHigh\":%f, "
                       "\"BidLow\":%f, \"BidClose\":%f, \"AskOpen\":%f, "
                       "\"AskHigh\":%f, \"AskLow\":%f, \"AskClose\":%f, "
                       "\"Volume\":%i},",
                       sTime.c_str(), reader->getBidOpen(ii),
                       reader->getBidHigh(ii), reader->getBidLow(ii),
                       reader->getBidClose(ii), reader->getAskOpen(ii),
                       reader->getAskHigh(ii), reader->getAskLow(ii),
                       reader->getAskClose(ii), reader->getVolume(ii));
              // cout << buffer << endl;
              prices = buffer + prices;
            } else {
              // printf("DateTime=%s, Bid=%f, Ask=%f\n", sTime,
              // reader->getBid(ii), reader->getAsk(ii));
              char buffer[512];
              snprintf(buffer, sizeof(buffer),
                       "{\"DateTime\":\"%s\", \"Bid\":%f, \"Ask\":%f},",
                       sTime.c_str(), reader->getBid(ii), reader->getAsk(ii));
              // cout << buffer << endl;
              prices = buffer + prices;
            }
          }
        }
      }
    }
  }
}

void printSampleParams(std::string &sProcName, LoginParams *loginParams,
                       SampleParams *sampleParams) {
  std::cout << "Running " << sProcName << " with arguments:" << std::endl;

  // Login (common) information
  if (loginParams) {
    std::cout << loginParams->getLogin() << " * " << loginParams->getURL()
              << " " << loginParams->getConnection() << " "
              << loginParams->getSessionID() << " " << loginParams->getPin()
              << std::endl;
  }

  // Sample specific information
  if (sampleParams) {
    std::cout << "Instrument='" << sampleParams->getInstrument() << "', "
              << "Timeframe='" << sampleParams->getTimeframe() << "', ";
    if (isNaN(sampleParams->getDateFrom())) {
      std::cout << "DateFrom='', ";
    } else {
      char sDateFrom[20];
      formatDate(sampleParams->getDateFrom(), sDateFrom);
      std::cout << "DateFrom='" << sDateFrom << "', ";
    }
    if (isNaN(sampleParams->getDateTo())) {
      std::cout << "DateTo='', ";
    } else {
      char sDateTo[20];
      formatDate(sampleParams->getDateTo(), sDateTo);
      std::cout << "DateTo='" << sDateTo << "', ";
    }
    std::cout << std::endl;
  }
}

void printHelp(std::string &sProcName) {
  std::cout << sProcName << " sample parameters:" << std::endl << std::endl;

  std::cout << "/login | --login | /l | -l" << std::endl;
  std::cout << "Your user name." << std::endl << std::endl;

  std::cout << "/password | --password | /p | -p" << std::endl;
  std::cout << "Your password." << std::endl << std::endl;

  std::cout << "/url | --url | /u | -u" << std::endl;
  std::cout
      << "The server URL. For example, http://www.fxcorporate.com/Hosts.jsp."
      << std::endl
      << std::endl;

  std::cout << "/connection | --connection | /c | -c" << std::endl;
  std::cout << "The connection name. For example, \"Demo\" or \"Real\"."
            << std::endl
            << std::endl;

  std::cout << "/sessionid | --sessionid " << std::endl;
  std::cout << "The database name. Required only for users who have accounts "
               "in more than one database. Optional parameter."
            << std::endl
            << std::endl;

  std::cout << "/pin | --pin " << std::endl;
  std::cout << "Your pin code. Required only for users who have a pin. "
               "Optional parameter."
            << std::endl
            << std::endl;

  std::cout << "/instrument | --instrument | /i | -i" << std::endl;
  std::cout << "An instrument which you want to use in sample. For example, "
               "\"EUR/USD\"."
            << std::endl
            << std::endl;

  std::cout << "/timeframe | --timeframe " << std::endl;
  std::cout << "Time period which forms a single candle. For example, m1 - for "
               "1 minute, H1 - for 1 hour."
            << std::endl
            << std::endl;

  std::cout << "/datefrom | --datefrom " << std::endl;
  std::cout << "Date/time from which you want to receive historical prices. If "
               "you leave this argument as it is, it will mean from last "
               "trading day. Format is \"m.d.Y H:M:S\". Optional parameter."
            << std::endl
            << std::endl;

  std::cout << "/dateto | --dateto " << std::endl;
  std::cout << "Datetime until which you want to receive historical prices. If "
               "you leave this argument as it is, it will mean to now. Format "
               "is \"m.d.Y H:M:S\". Optional parameter."
            << std::endl;
}

bool checkObligatoryParams(LoginParams *loginParams,
                           SampleParams *sampleParams) {
  /* Check login parameters. */
  if (strlen(loginParams->getLogin()) == 0) {
    std::cout << LoginParams::Strings::loginNotSpecified << std::endl;
    return false;
  }
  if (strlen(loginParams->getPassword()) == 0) {
    std::cout << LoginParams::Strings::passwordNotSpecified << std::endl;
    return false;
  }
  if (strlen(loginParams->getURL()) == 0) {
    std::cout << LoginParams::Strings::urlNotSpecified << std::endl;
    return false;
  }
  if (strlen(loginParams->getConnection()) == 0) {
    std::cout << LoginParams::Strings::connectionNotSpecified << std::endl;
    return false;
  }

  /* Check other parameters. */
  if (strlen(sampleParams->getInstrument()) == 0) {
    std::cout << SampleParams::Strings::instrumentNotSpecified << std::endl;
    return false;
  }
  if (strlen(sampleParams->getTimeframe()) == 0) {
    std::cout << SampleParams::Strings::timeframeNotSpecified << std::endl;
    return false;
  }

  bool bIsDateFromNotSpecified = false;
  bool bIsDateToNotSpecified = false;
  DATE dtFrom = sampleParams->getDateFrom();
  DATE dtTo = sampleParams->getDateTo();
  char sDateFrom[20];
  char sDateTo[20];

  time_t tNow = time(NULL); // get time now
  struct tm *tmNow = gmtime(&tNow);
  DATE dtNow = 0;
  CO2GDateUtils::CTimeToOleTime(tmNow, &dtNow);

  if (isNaN(dtFrom)) {
    bIsDateFromNotSpecified = true;
    dtFrom = 0;
    sampleParams->setDateFrom(dtFrom);
  } else {
    if (dtFrom - dtNow > 0.0001) {
      formatDate(dtFrom, sDateFrom);
      std::cout << "'DateFrom' value " << dtFrom << " is invalid" << std::endl;
      return false;
    }
  }

  if (isNaN(dtTo)) {
    bIsDateToNotSpecified = true;
    dtTo = 0;
    sampleParams->setDateTo(dtTo);
  } else {
    if (!bIsDateFromNotSpecified && dtFrom - dtTo > 0.001) {
      formatDate(dtTo, sDateTo);
      std::cout << "'DateTo' value " << dtTo << " is invalid" << std::endl;
      return false;
    }
  }

  return true;
}

/*
curl -X POST -H "Content-Type: application/json" -d '{"symbol": "EUR/USD",
"timeFrom": "10.10.2023 15:00:00", "timeTo": "10.10.2023 15:01:00", "action":
"get"}' http://127.0.0.1:5000/hist/
*/
