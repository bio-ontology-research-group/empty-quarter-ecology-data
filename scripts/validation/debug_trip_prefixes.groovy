@Grab(group='org.apache.poi', module='poi-ooxml', version='5.2.5')
import org.apache.poi.ss.usermodel.*
import org.apache.poi.xssf.usermodel.XSSFWorkbook
import java.io.File

def excelFile = new File("data/metadata/samples/Sample_Mastersheet.xlsx")
FileInputStream fis = new FileInputStream(excelFile)
Workbook workbook = new XSSFWorkbook(fis)

["Trip1", "Trip2", "Trip3", "Trip4", "Trip5"].each { name ->
    Sheet sheet = workbook.getSheet(name)
    if (sheet) {
        Row row = sheet.getRow(1)
        if (row) {
            def headers = [:]
            sheet.getRow(0).each { headers[it.toString().toLowerCase()] = it.getColumnIndex() }
            def nameCell = row.getCell(headers["name"])
            println "${name} first sample name: ${nameCell}"
        }
    }
}
